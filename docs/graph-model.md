# Ripple graph model

**DRAFT.** Describes what `backend/app/graph/` and `backend/queries/` do today. Sections marked **TODO** are being built in a parallel stream; their details are intentionally not written here.

Ripple stores commitments, the work they depend on, and the decisions that set delivery forecasts in FalkorDB (a Redis-based graph database queried with Cypher). Impact, owner and history answers come from graph queries over those records. The Python code groups rows and applies the status/owner rules below; fixtures under `fixtures/harbor/expected/` are test assertions only, never a runtime lookup.

All data is synthetic (the "Harbor" fixtures: four customers, six work items).

## Nodes

All times are UTC epoch milliseconds (integers). Every label has an index on `id`.

| Label | Properties | Notes |
| --- | --- | --- |
| `Customer` | `id`, `name`, `synthetic_contract_value` | e.g. `cust_acme` |
| `Commitment` | `id`, `title`, `due_at`, `status`, `source_id`, `quote` | only `status = 'open'` commitments are analysed |
| `WorkItem` | `id`, `name`, `kind` | `kind` is `feature`, `project` or `component` |
| `Person` | `id`, `name` | |
| `Team` | `id`, `name` | |
| `Source` | `id`, `type`, `title`, `body`, `source_timestamp`, `content_hash` | `body` is the exact text; `content_hash` is SHA-256 of it |
| `Decision` | `id`, `summary`, `decided_at`, `status`, `source_id`, `quote` | canonical existing decision is `DEC-12` |
| `Forecast` | `id`, `available_at`, `valid_from`, `valid_to` (absent = open), `status`, `source_id`, `quote` | only `status = 'accepted'` forecasts count |
| `Alias` | `id`, `text`, `text_lower`, `kind` | lookup text such as "permissions"; points at every candidate entity |
| `GraphState` | `id` (`'workspace'`), `dataset_id`, `revision` | singleton version record, see [Versioning](#evidence_version) |
| `RequestRecord` | | **TODO** (stream A): durable replay record for mutations |

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

`evidence_version = "<dataset_id>:<revision>"`, read from `GraphState`. Seeding creates a new random `dataset_id` and `revision` 0. Confirmed knowledge changes are meant to increment `revision` (**TODO**: confirm_decision). Multi-query reads (impacts, history) read the version before and after; if it moved they retry, up to 3 attempts, then raise `InconsistentRead`. Clients treat the string as opaque.

## Seed, reset and smoke test

Run from the repo root with the venv that has the `falkordb` client:

```bash
# seed (replaces the whole graph) and print the four baseline statuses plus one source
~/.venvs/ripple-graph/bin/python -m backend.app.graph.smoke

# graph tests against a running FalkorDB (each test uses a throwaway ripple_test_<random> graph)
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
```

Settings: `FALKORDB_HOST`, `FALKORDB_PORT` (default 6379), `FALKORDB_PASSWORD`, `RIPPLE_GRAPH_NAME` (default `ripple_demo`). `GraphRepository.seed_demo(fixtures_dir, scenario=None)` deletes the graph, validates the fixtures (exact quotes, known IDs, no dependency cycle), loads them and creates a new `GraphState`. Invalid fixtures are rejected before anything is written. The optional scenario overlay is a test helper, not the live update flow.

## TODO sections (stream A)

- **TODO: confirm_decision**: version-gated cutover, source/decision creation, revision increment.
- **TODO: RequestRecord replay**: properties, idempotency scope, replay rules.
- **TODO: Actions**: `save_action` / `list_actions` storage.

## Known limitations

- **No automatic downstream replanning.** When `wi_permissions` slips, the forecasts of `wi_identity_migration` and `wi_sso` stay as recorded. Ripple flags the conflict and shows the recorded forecast beside it; it does not compute a new schedule.
- **Dependencies are static.** `DEPENDS_ON` edges come from the fixtures and are not inferred or updated from new notes.
- **Deterministic seed mappings.** Baseline entities, edges and forecasts are mapped from the synthetic fixtures by hand, not extracted by a model.
- Dependency expansion is bounded at 4 hops; deeper chains are flagged, not followed.
- Synthetic data only (one dataset, four customers).
