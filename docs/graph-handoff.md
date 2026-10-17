# Graph layer handoff

From Ashwin (graph owner) to Pavan (API/infrastructure) and Abhijeet (agent tools). Branch `feat/ashwin-graph`, last commit `e44a07e`. The graph model, rules and verification results are in [graph-model.md](graph-model.md); this page covers only what you need to integrate.

## 1. Database requirements (for Compose)

| Item | Value |
| --- | --- |
| Image | `falkordb/falkordb:v4.22.1` (tested) |
| Python client | `falkordb==1.8.0` (pulls `redis` 8.x); tested on Python 3.11 |
| Port | 6379 inside the container |
| Persistent volume | mount at `/var/lib/falkordb/data` (the image's data directory) |
| Shutdown | stop gracefully (`docker compose stop` / `restart`). With the default RDB settings, data survived `docker restart`; a hard `docker kill` lost writes made since the last snapshot. Add `--appendonly yes` (via `REDIS_ARGS` or `FALKORDB_ARGS`) if crash safety matters; this is untested |
| Environment | `FALKORDB_HOST` (default `localhost`), `FALKORDB_PORT` (`6379`), `FALKORDB_PASSWORD` (optional, untested), `RIPPLE_GRAPH_NAME` (default `ripple_demo`) |

`GraphClient(host=None, port=None, password=None, graph_name=None, timeout_seconds=5.0)` reads those variables when arguments are omitted, so the settings module can pass values explicitly instead.

## 2. Using the repository

```python
from app.graph.client import GraphClient          # or backend.app.graph..., relative imports work either way
from app.graph.repository import GraphRepository

repo = GraphRepository(GraphClient())
```

- The repository is **synchronous**. Call it from FastAPI sync handlers or a threadpool, never directly on the event loop.
- Every method returns plain dicts, lists, strings and ints (epoch ms in UTC). No FalkorDB objects leak out.
- The graph package imports nothing from the API or AI packages.

| Method | Returns / notes |
| --- | --- |
| `seed_demo(fixtures_dir, scenario=None)` | Validates, then replaces the graph with `fixtures/harbor`. Returns the new `dataset_id`; the version becomes `<dataset_id>:0`. `scenario` is for tests only |
| `get_version()` | Opaque `"<dataset_id>:<revision>"` |
| `list_impacts(as_of_ms)` | `{evidence_version, as_of, impacts, completeness}` in the contract's `ImpactResponse` shape; all open commitments, controls included |
| `get_evidence(commitment_id, as_of_ms)` | One `Impact` |
| `get_owners(commitment_id, as_of_ms)` | `{engineering_owner, account_owner, warnings}`. **Takes `as_of_ms`**, which the contract's list omitted, because the engineering owner depends on the current blockers |
| `get_source(source_id)` | `{id, type, title, body, source_timestamp, content_hash}` |
| `get_history(work_item_id)` | `{evidence_version, forecasts:[{id, available_at, valid_from, valid_to, decision_id, supersedes_id, decision_summary, citations}]}` |
| `resolve_entity(query, kind=None)` | `[{id, kind, name, matched_by}]`: case-insensitive exact match on id, name or alias. Returns **every** candidate and never picks one. Kinds: `customer`, `commitment`, `work_item`, `person`, `team`, `decision` |
| `confirm_decision(proposal, source, expected_version, idempotency_key, now_ms=None)` | `{decision_id, evidence_version, changed_work_item_ids}` |
| `save_action(action, expected_version, idempotency_key, now_ms=None)` | `{action_id, status: 'reviewed', evidence_version, created_at}` |
| `list_actions(commitment_id)` | `{evidence_version, actions:[{id, commitment_id, kind, assignee_id, body, citations, based_on_decision_ids, status, evidence_version, created_at}]}`. Each Action keeps the version it was saved with; mark it for re-review when that differs from the top-level version |

Inputs for the two writes:

- `proposal`: `{work_item_id, available_at, effective_at, owner_id, evidence_quote, supersedes_id?}`. Set `effective_at` to the server's `preview_created_at`.
- `source`: `{id, type, title, body, source_timestamp}`. `content_hash` is computed by the graph layer.
- `action`: `{commitment_id, kind, assignee_id, body, citations:[{source_id, quote}], based_on_decision_ids}`

Pass `now_ms` only in tests; it defaults to server time.

## 3. Errors to map

All errors subclass `GraphError` and carry `.message` and `.details`. Never return a raw exception to the client.

| Error | HTTP (contract) |
| --- | --- |
| `StaleEvidence` | 409 `stale_evidence` |
| `IdempotencyConflict` | 409 `idempotency_conflict` |
| `ReviewRequired` | 422 `review_required` |
| `NotFound` | 404 |
| `GraphUnavailable` | 503 `graph_unavailable` |
| `InconsistentRead` | suggested: retry the read once, then 503 (not in the contract) |
| `FixtureError` | seed/reset only; 500 or an operator error |

Check order inside `confirm_decision` and `save_action`: replay → stale version → validation → write. A completed request with the same key and payload replays its stored result even after later revisions. Your confirm route can call the repository directly after checking preview expiry (410 stays in your layer).

## 4. Behaviour you should know

1. **Warnings are not a separate field on `Impact`.** The contract has none, so each warning is a prefix on a `reasons` string, for example `"missing_forecast: wi_x has no active accepted forecast"`. The codes are `missing_forecast`, `conflicting_forecasts`, `missing_forecast_provenance`, `missing_engineering_owner`, `ambiguous_engineering_owner`, `missing_account_owner`, `ambiguous_account_owner`, `depth_limit_exceeded`, `missing_requirement` and `missing_customer`. A confirmed blocker reason starts with `dependency_after_due`. `completeness.warnings` repeats them as `"<commitment_id>: <reason>"`. If you would rather have `Impact.warnings`, propose a contract change.
2. **Missing customer:** a commitment without a `HAS_COMMITMENT` edge returns `customer: {"id": "", "name": ""}`, because the contract types are non-nullable strings, plus the `missing_customer` reason.
3. **History has two extra fields**, `supersedes_id` and `decision_summary`, for the lineage question ("Why did the permissions forecast change?"). They need your agreement. If rejected, they are dropped in one query.
4. **A malformed `expected_version` raises `StaleEvidence` (409).** It could arguably be 422 `invalid_input`; your call.
5. **Server-owned lineage:** the new Decision always supersedes the decision behind the forecast that is currently in force. A caller's `supersedes_id` is only checked, never trusted, so a second update does not need to name the first one.
6. **Delivery dates are never compared with today.** Judges may run this after October 2026, so a past `available_at` is accepted. Please keep the preview validation consistent with this.
7. **Repeat notes are rejected.** Confirming a note whose date equals the current forecast, or the same source/work item/date again, raises `ReviewRequired`. A new note needs a new date or source.
8. **Validation is structural.** `save_action` checks that decisions exist and that citation quotes are exact substrings of stored sources. It does not check that the decisions are relevant to the commitment, or that edited prose is true.
9. **Mutations assume one API worker**, as the contract says. Correctness under overlapping requests comes from the version gate and the existing-record check inside each write statement; there is no database uniqueness constraint.

## 5. Open questions for kickoff

| # | Question | State |
| --- | --- | --- |
| 1 | Should `supersedes_id` be server-derived rather than model-extracted? | Built server-side (item 5). Extraction may still propose it as a cross-check |
| 2 | Should delivery dates never be validated against the current time? | Graph side done (item 6); the preview validation still has to match |
| 3 | Should history include `supersedes_id` and `decision_summary`? | Built (item 3); awaiting agreement |

## 6. Commands

```bash
# local database for development
docker run -d --name ripple-falkordb-dev -p 6379:6379 falkordb/falkordb:v4.22.1

# seed the demo graph and print the four baseline statuses
~/.venvs/ripple-graph/bin/python -m backend.app.graph.smoke

# graph tests (85; restart and timing checks are opt-in)
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
PYTHONDONTWRITEBYTECODE=1 RIPPLE_RESTART_TEST=1 RIPPLE_TIMINGS=1 \
  ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
```

The venv path is Ashwin's local setup; once the backend manifest includes `falkordb`, use the project environment instead.

## 7. For `docs/verification.md`

Copy the [Verification results](graph-model.md#verification-results) section. It holds the observed outcomes for the baseline, the October 28 confirm, history, Actions, the edge-removal proof, restart persistence and timings.

## 8. For Abhijeet's agent tools

| Tool | Repository call |
| --- | --- |
| `resolve_entity` | `resolve_entity(query, kind)`: preserve ambiguity, never take the first candidate |
| `find_impacted_commitments` | `list_impacts(as_of_ms)` |
| `get_evidence` | `get_evidence(commitment_id, as_of_ms)` and `get_source(source_id)` |
| `get_owners` | `get_owners(commitment_id, as_of_ms)` |
| `get_forecast_history` | `get_history(work_item_id)`: use `decision_id`, `supersedes_id` and citations for lineage |

All of these are reads. Only the API's confirm and save routes call the two write methods; agent tools must not. Pass through the `evidence_version` each call returns.
