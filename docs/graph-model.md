# Ripple graph model

**DRAFT.** Describes what `backend/app/graph/` and `backend/queries/` do today, written from the code. The only open item is the [Verification results](#verification-results) section.

Ripple stores commitments, the work they depend on, and the decisions that set delivery forecasts in FalkorDB (a Redis-based graph database queried with Cypher). Impact, owner and history answers come from graph queries over those records. The Python code groups rows and applies the status/owner rules below; fixtures under `fixtures/harbor/expected/` are test assertions only, never a runtime lookup.

All data is synthetic (the "Harbor" fixtures: four customers, six work items).

## Nodes

All times are UTC epoch milliseconds (integers). Every label, including `GraphState`, `Action` and `RequestRecord`, has an index on `id`.

| Label | Properties | Notes |
| --- | --- | --- |
| `Customer` | `id`, `name`, `synthetic_contract_value` | e.g. `cust_acme` |
| `Commitment` | `id`, `title`, `due_at`, `status`, `source_id`, `quote` | only `status = 'open'` commitments are analysed |
| `WorkItem` | `id`, `name`, `kind` | `kind` is `feature`, `project` or `component` |
| `Person` | `id`, `name` | |
| `Team` | `id`, `name` | |
| `Source` | `id`, `type`, `title`, `body`, `source_timestamp`, `content_hash` | `body` is the exact text; `content_hash` is SHA-256 of it |
| `Decision` | `id`, `summary`, `decided_at`, `status`, `source_id`, `quote` | canonical existing decision is `DEC-12` |
| `Forecast` | `id`, `available_at`, `valid_from`, `valid_to` (absent = open), `status`, `source_id`, `quote`; forecasts created by `confirm_decision` also have `recorded_at` | only `status = 'accepted'` forecasts count |
| `Alias` | `id`, `text`, `text_lower`, `kind` | lookup text such as "permissions"; points at every candidate entity |
| `GraphState` | `id` (`'workspace'`), `dataset_id`, `revision` | singleton version record, see [Versioning](#evidence_version) |
| `Action` | `id`, `kind`, `body`, `status` (`'reviewed'`), `created_at`, `evidence_version`, `citations_json` | saved by `save_action`; `id` = `act_` + first 16 hex chars of SHA-256(dataset_id, idempotency_key); `citations_json` is the citation list as canonical JSON |
| `RequestRecord` | `id`, `dataset_id`, `operation`, `idempotency_key`, `request_hash`, `result_json`, `committed_at` | one per completed mutation; `id` = `req_` + first 32 hex chars of SHA-256(dataset_id, operation, key); see [Replay](#requestrecord-replay) |

## Relationships

Edges marked "provenance" carry `source_id` and `quote` properties; `quote` is an exact substring of that Source's `body` (checked when fixtures are validated, before anything is written).

| Edge | Direction | Provenance |
| --- | --- | --- |
| `HAS_COMMITMENT` | `Customer → Commitment` | yes |
| `REQUIRES` | `Commitment → WorkItem` | yes |
| `DEPENDS_ON` | `WorkItem → WorkItem` (the dependent points at what it needs) | yes |
| `OWNS` | `Person → WorkItem` (engineering owner) | yes |
| `ACCOUNT_OWNER` | `Person → Customer` | yes |
| `MEMBER_OF` | `Person → Team` | yes |
| `RESPONSIBLE_FOR` | `Team → WorkItem` | yes |
| `HAS_FORECAST` | `WorkItem → Forecast` | no |
| `ESTABLISHES` | `Decision → Forecast` | no |
| `REVISES` | `Decision → WorkItem` | no |
| `SUPERSEDES` | `Decision → Decision` (newer → older) | no |
| `SUPPORTED_BY` | `Commitment`, `Forecast` or `Decision → Source` | yes |
| `REFERS_TO` | `Alias → entity` (one edge per candidate, so an ambiguous alias has several) | no |
| `ADDRESSES` | `Action → Commitment` | no |
| `ASSIGNED_TO` | `Action → Person` | no |
| `BASED_ON` | `Action → Decision` (one edge per decision the Action relies on) | no |

### Decision `-ESTABLISHES->` Forecast

Each forecast has one establishing Decision, and that Decision has a `SUPPORTED_BY` Source. The permissions baseline forecast is established by `DEC-12`; every other baseline forecast has its own `dec_baseline_<work_item>` Decision. History and blockers read `decision_id` from this edge only. They never guess it from other Decisions that `REVISES` the same work item, because a work item can be revised many times. `REVISES` records what a Decision is about; `ESTABLISHES` records which forecast it created.

A forecast with no establishing Decision is not a confirmed blocker: the commitment gets a `missing_forecast_provenance` warning instead.

## Evidence path: Acme after the October 28 update

Produced by seeding the baseline plus the `scn_history_update_boundary` fixture scenario (an `apply_update` operation) and calling `get_evidence("com_acme_sso", …)`. The Decision and Forecast IDs below are that scenario's; a live update would have server-generated IDs.

```text
cust_acme ──HAS_COMMITMENT──▶ com_acme_sso ──REQUIRES──▶ wi_sso ──DEPENDS_ON──▶ wi_identity_migration ──DEPENDS_ON──▶ wi_permissions
          src_acme_handoff               src_sso_plan           src_sso_plan                         src_identity_plan
```

| Edge | Source | Quote |
| --- | --- | --- |
| `cust_acme → com_acme_sso` | `src_acme_handoff` | Commitment: Enterprise SSO delivered by October 23, 2026. |
| `com_acme_sso → wi_sso` | `src_sso_plan` | Acme's Enterprise SSO commitment requires the SSO feature. |
| `wi_sso → wi_identity_migration` | `src_sso_plan` | The SSO feature depends on the identity migration project. |
| `wi_identity_migration → wi_permissions` | `src_identity_plan` | The identity migration project depends on the permissions service. |

Blocker (the end of the chain):

- Forecast `fc_scn_permissions_oct28` on `wi_permissions`: `available_at` = end of 2026-10-28 IST, open interval, accepted.
- Established by Decision `dec_scn_permissions_oct28`, which `SUPERSEDES` `DEC-12`. Its source is `src_scn_update_notes`: "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12."
- Acme is due end of 2026-10-23 IST, so `available_at > due_at` and the status is `date_conflict`.
- Owners: engineering owner `person_priya` ("Priya owns the permissions service.", `src_owners`); account owner `person_maya` ("Maya is the account owner for Acme.", `src_owners`).

The recorded forecast for `wi_sso` itself is still October 23. It is not recalculated (see [Limitations](#known-limitations)).

## Central impact query

`backend/queries/impact_blockers.cypher` (parameters `$as_of` epoch ms and `$cid`, an optional commitment filter):

```cypher
MATCH (k:Commitment {status: 'open'})
WHERE $cid IS NULL OR k.id = $cid
MATCH (k)-[:REQUIRES]->(root:WorkItem)
MATCH (root)-[:DEPENDS_ON*0..4]->(w:WorkItem)-[:HAS_FORECAST]->(f:Forecast)
WHERE f.status = 'accepted'
  AND f.valid_from <= $as_of
  AND (f.valid_to IS NULL OR $as_of < f.valid_to)
  AND f.available_at > k.due_at
OPTIONAL MATCH (d:Decision)-[:ESTABLISHES]->(f)
RETURN DISTINCT k.id, w.id, w.name, f.id, f.available_at, f.source_id, f.quote,
                d.id, d.source_id, d.quote
```

Companion queries in the same directory: `impact_paths.cypher` (every bounded path with edge sources and quotes), `impact_forecast_counts.cypher` (active forecasts per work item), `impact_depth_probe.cypher` (below), `open_commitments`, `owners`, `account_owners`, `work_items`.

## Status rules

Per open commitment (all open commitments are returned, even ones with a missing customer or requirement link):

- `date_conflict`: at least one confirmed blocker. A blocker is a work item within the bound whose single active accepted forecast has `available_at > due_at` (**strictly** greater; same day is not a conflict) and an establishing Decision. Other warnings are kept in `reasons`.
- `needs_verification`: no confirmed blocker, but a warning exists: `missing_forecast`, `conflicting_forecasts` (several active accepted forecasts on one work item, which is never treated as a blocker), `missing_forecast_provenance`, `missing_engineering_owner`, `ambiguous_engineering_owner`, `missing_account_owner`, `ambiguous_account_owner`, `missing_requirement`, `missing_customer` or `depth_limit_exceeded`.
- `no_detected_conflict`: no blocker and no warning. This is limited to the recorded model and the bounded paths.

**Bound.** Dependencies are followed up to 4 `DEPENDS_ON` hops from the required work item. `impact_depth_probe.cypher` looks for a path of exactly 5 hops (`DEPENDS_ON*5..5`). If one exists, the commitment gets `depth_limit_exceeded` and the response sets `completeness.truncated`. Dependency cycles are rejected when fixtures are imported, before anything is written.

**Point in time.** Active means `valid_from <= as_of < valid_to` (open when `valid_to` is absent).

## Owner rules

- Engineering owner for a `date_conflict`: the single owner across all blocking work items. Different owners, or a blocker with none, gives `null` plus a warning.
- With no blocker: the single owner of the required root work item (if there are several roots, they must share one owner).
- Account owner: the Customer's single `ACCOUNT_OWNER`; none or several gives `null` plus a warning.
- Missing or ambiguous ownership makes the result `needs_verification`, unless there is a `date_conflict`, which takes precedence and keeps the warning.

## Time conventions

- Stored times are integer UTC epoch milliseconds. Fixtures contain only ISO strings and are converted in `backend/app/graph/timeutil.py`.
- A date-only value ("2026-10-23") means the end of that day in Asia/Kolkata: next IST midnight minus 1 ms. Used for `due_at` and `available_at`.
- Instants (`valid_from`, `valid_to`, `decided_at`, `source_timestamp`) are ISO 8601 with an offset.
- Forecast intervals are half-open: `[valid_from, valid_to)`. When an update closes a forecast, the old `valid_to` equals the new `valid_from`: no gap, no overlap. Closed forecasts are kept, not deleted.

## Forecast history

`GraphRepository.get_history(work_item_id)` returns `{evidence_version, forecasts: [...]}`, ordered by `valid_from` ascending. Each forecast has `id`, `available_at`, `valid_from`, `valid_to` (null when open), `decision_id`, `citations` (the forecast's quote, then its establishing Decision's quote, skipping an identical duplicate), and two lineage fields: `supersedes_id` (that Decision's `SUPERSEDES` target, or null) and `decision_summary`. Those two fields are pending agreement with Pavan and are easy to drop. An unknown work item raises `NotFound`; a known one with no accepted forecast returns an empty list. Queries: `history_forecasts.cypher`, `history_citations.cypher`.

## evidence_version

`evidence_version = "<dataset_id>:<revision>"`, read from `GraphState`. Seeding creates a new random `dataset_id` and `revision` 0. A confirmed decision (`confirm_decision`) increments `revision` by one, in the same statement as the new facts. Saving an Action does not change it. Seeding again (reset) creates a new `dataset_id`, so a version string from before the reset can never match. Multi-query reads (impacts, history) read the version before and after; if it moved they retry, up to 3 attempts, then raise `InconsistentRead`. Clients treat the string as opaque.

## Seed, reset and smoke test

Run from the repo root with the venv that has the `falkordb` client:

```bash
# seed (replaces the whole graph) and print the four baseline statuses plus one source
~/.venvs/ripple-graph/bin/python -m backend.app.graph.smoke

# graph tests against a running FalkorDB (each test uses a throwaway ripple_test_<random> graph)
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
```

Settings: `FALKORDB_HOST`, `FALKORDB_PORT` (default 6379), `FALKORDB_PASSWORD`, `RIPPLE_GRAPH_NAME` (default `ripple_demo`). `GraphRepository.seed_demo(fixtures_dir, scenario=None)` deletes the graph, validates the fixtures (exact quotes, known IDs, no dependency cycle), loads them and creates a new `GraphState`. Invalid fixtures are rejected before anything is written. The optional scenario overlay is a test helper, not the live update flow.

## Confirming a decision

`GraphRepository.confirm_decision(proposal, source, expected_version, idempotency_key, now_ms=None)` (logic in `backend/app/graph/writes.py`) turns an approved note into a new accepted forecast. `proposal` has `work_item_id`, `available_at`, `effective_at`, `owner_id`, `evidence_quote` and optionally `supersedes_id`; `source` has `id`, `type`, `title`, `body`, `source_timestamp`. It returns `{decision_id, evidence_version, changed_work_item_ids}`. `now_ms` defaults to server time and exists for tests.

### Order of checks

1. **Replay.** If a `RequestRecord` exists for this dataset, operation and key, return its stored result (or raise `IdempotencyConflict`). This comes first, so a completed request still replays after later revisions. A malformed version string raises `StaleEvidence`.
2. **Stale check.** `expected_version` must equal the current version, else `StaleEvidence`.
3. **Validation.** No writes; see the table below.
4. **ID-collision check.** The new `dec_` and `fc_` IDs must not already exist.
5. **One version-gated write** (`confirm_decision.cypher`). If it matches nothing, the code re-checks for a replay (a racing identical request may have won), then reports `StaleEvidence` if the version moved, otherwise `ReviewRequired`.

### Validation rules

| Rule | Error |
| --- | --- |
| Work item exists | `NotFound` |
| Exactly one active accepted forecast (`valid_to` absent) | `ReviewRequired` |
| That forecast has exactly one establishing Decision | `ReviewRequired` |
| `owner_id` is the work item's one recorded `OWNS` owner (ownership changes are not handled here) | `ReviewRequired` |
| `available_at` differs from the active forecast's (no-op updates rejected) | `ReviewRequired` |
| `evidence_quote` is non-empty and an exact substring of `source.body` | `ReviewRequired` |
| `active.valid_from < effective_at <= now` | `ReviewRequired` |
| `supersedes_id`, if given, is the active forecast's establishing Decision | `ReviewRequired` |
| If a Source with this `id` already exists, its content hash matches `source.body` | `ReviewRequired` |
| Generated `dec_`/`fc_` IDs are not already used (a repeat of the same note) | `ReviewRequired` |
| Version matches / key not reused with a different request | `StaleEvidence` / `IdempotencyConflict` |

Time rules: `effective_at` must be strictly after the active forecast's `valid_from` and no later than the current time, so the interval stays forward-moving and a preview time slightly earlier than confirmation is fine. Delivery dates (`available_at`) are never compared with the current time; a future or past delivery date is accepted if the other rules pass.

### What gets written

- `SUPERSEDES` is derived from the graph: the new Decision points at the Decision that establishes the old active forecast. The caller's `supersedes_id` is only checked against it, never trusted.
- IDs are deterministic: `dec_` / `fc_` + the first 16 hex chars of SHA-256(dataset_id, source id, work item id, `available_at`). A second note for the same source, work item and date therefore collides and is rejected as a repeat note. The same date from a different source gets different IDs.
- The Decision's summary is `"<work item name> delivery set to <YYYY-MM-DD> (IST)"`, for example "Permissions service delivery set to 2026-10-28 (IST)". It is `decided_at` = `effective_at`, status `approved`.
- The old forecast is closed (`valid_to = effective_at`) and kept; the new forecast starts at `effective_at` and is open.
- The Source is created if it is new, otherwise reused.

### The version gate

`backend/queries/confirm_decision.cypher`:

```cypher
MATCH (g:GraphState {id: 'workspace', dataset_id: $dataset, revision: $expected_revision})
MATCH (wi:WorkItem {id: $work_item_id})-[:HAS_FORECAST]->(old:Forecast {status: 'accepted'})
WHERE old.valid_to IS NULL
MATCH (old_dec:Decision)-[:ESTABLISHES]->(old)
SET old.valid_to = $effective_at
MERGE (s:Source {id: $source_id})
  ON CREATE SET s.type = $source_type, s.title = $source_title, s.body = $source_body,
                s.source_timestamp = $source_timestamp, s.content_hash = $content_hash
CREATE (fc:Forecast {id: $forecast_id, available_at: $available_at, valid_from: $effective_at,
                     status: 'accepted', recorded_at: $now, source_id: $source_id, quote: $quote})
CREATE (dec:Decision {id: $decision_id, summary: $summary, decided_at: $effective_at,
                      status: 'approved', source_id: $source_id, quote: $quote})
CREATE (wi)-[:HAS_FORECAST]->(fc)
CREATE (dec)-[:ESTABLISHES]->(fc)
CREATE (dec)-[:REVISES]->(wi)
CREATE (dec)-[:SUPERSEDES]->(old_dec)
CREATE (dec)-[:SUPPORTED_BY {source_id: $source_id, quote: $quote}]->(s)
CREATE (fc)-[:SUPPORTED_BY {source_id: $source_id, quote: $quote}]->(s)
SET g.revision = g.revision + 1
CREATE (:RequestRecord {id: $request_id, dataset_id: $dataset, operation: 'confirm_decision',
                        idempotency_key: $key, request_hash: $request_hash,
                        result_json: $result_json, committed_at: $now})
RETURN dec.id, g.revision
```

The first `MATCH` binds the `GraphState` node for the expected dataset and revision. In Cypher each later clause runs once per row produced so far, so if that match finds nothing (stale version, or a reset dataset) there are no rows and nothing after it runs: no forecast closed, no node created, no revision change. If two writers hold the same revision, the first to run increments it, and the second's match then fails. Validation in Python gives readable errors; this gate is what makes overlapping writers safe.

## RequestRecord replay

- **Scope.** A request is identified by dataset, operation (`confirm_decision` or `save_action`) and idempotency key. The record's `id` is a hash of those three; lookup also matches the three properties.
- **`request_hash`.** SHA-256 of canonical JSON (sorted keys, no whitespace). For `confirm_decision`: the proposal (keys with null values dropped), the whole source dict (including its body) and `expected_version`. For `save_action`: the whole action and `expected_version`. The idempotency key is not in the hash because it is part of the scope; `now_ms` is not in it either.
- **Same key, same request** returns the stored `result_json` without writing anything.
- **Same key, different request** raises `IdempotencyConflict`.
- **Replay before version.** Because the replay check runs first, a request that already completed returns its original result even after later confirmations have moved the revision.
- **Reset.** Seeding creates a new `dataset_id`, and a version string carries the dataset. A request using an old-dataset version looks for a record in a dataset that no longer exists, finds none, and fails the stale check with `StaleEvidence`; it does not replay into the new data.
- **Atomicity.** The `RequestRecord` is created inside the same Cypher statement as the facts it describes, so both exist or neither does.

## Actions

`save_action(action, expected_version, idempotency_key, now_ms=None)` stores a reviewed draft; `list_actions(commitment_id)` reads them back. An Action is a stored draft: nothing is sent to Slack, a ticket system or a customer.

`action` has `commitment_id`, `kind` (`internal_escalation` or `customer_update`), `assignee_id`, `body`, `citations` (`[{source_id, quote}]`) and `based_on_decision_ids`. Checks run after the same replay and stale checks as above:

| Rule | Error |
| --- | --- |
| Commitment exists | `NotFound` |
| `assignee_id` is set and a Person exists | `NotFound` |
| `kind` is one of the two allowed values | `ReviewRequired` |
| `body` is a non-empty string | `ReviewRequired` |
| At least one citation; each has exactly `source_id` and `quote`, a non-empty quote | `ReviewRequired` |
| Each cited Source exists | `NotFound` |
| Each quote is an exact substring of its Source body | `ReviewRequired` |
| `based_on_decision_ids` is non-empty | `ReviewRequired` |
| Every listed Decision exists | `NotFound` |

These are structural checks: they show the quotes are real and the IDs exist, not that the body text is supported by them.

The write (`action_save.cypher`) uses the same `GraphState` gate but does **not** increment `revision`, so saving an Action never invalidates other clients' evidence. It creates the `Action`, its `ADDRESSES`, `ASSIGNED_TO` and `BASED_ON` edges and the `RequestRecord` in one statement. The result is `{action_id, status: 'reviewed', evidence_version, created_at}`, where `evidence_version` is the version the caller reviewed against.

`list_actions` returns that Action's saved `evidence_version` unchanged, alongside the current `evidence_version` of the response. When they differ, knowledge has changed since the Action was reviewed and the UI should mark it for re-review. Actions are listed oldest first.

## Typed errors

The graph layer raises these (`backend/app/graph/errors.py`). The HTTP mapping is **Pavan's API layer**, not implemented here; this table is the agreed intent.

| Error | Raised when | Expected HTTP |
| --- | --- | --- |
| `StaleEvidence` | version malformed or not current | 409 |
| `IdempotencyConflict` | key reused with a different request | 409 |
| `ReviewRequired` | a validation rule above failed; a fresh review is needed | 422 |
| `NotFound` | unknown work item, commitment, person, source, decision, or an unseeded graph | 404 |
| `GraphUnavailable` | FalkorDB unreachable or timed out | 503 |
| `InconsistentRead` | revision kept changing during a multi-query read (3 attempts) | retryable; the caller may retry the read |
| `FixtureError` | a seed/import was rejected (cycle, bad quote, unknown ID) | not an API error |

## Verification results

**TODO:** observed test results and query timings, to be added from the end-to-end verification run.

## Known limitations

- **No automatic downstream replanning.** When `wi_permissions` slips, the forecasts of `wi_identity_migration` and `wi_sso` stay as recorded. Ripple flags the conflict and shows the recorded forecast beside it; it does not compute a new schedule.
- **Dependencies are static.** `DEPENDS_ON` edges come from the fixtures and are not inferred or updated from new notes.
- **Deterministic seed mappings.** Baseline entities, edges and forecasts are mapped from the synthetic fixtures by hand, not extracted by a model.
- Action idempotency relies on mutations being serialised (one API worker). A knowledge confirmation is protected by the revision gate, but `save_action` does not change the revision, so two simultaneous identical `save_action` calls could both pass the gate.
- Dependency expansion is bounded at 4 hops; deeper chains are flagged, not followed.
- Synthetic data only (one dataset, four customers).
