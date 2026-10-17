# Ripple — shared implementation contract

Owners: Pavan maintains the API/wire contract; Ashwin owns graph semantics; Abhijeet owns AI interfaces; Jay owns frontend consumers. Freeze this together during the first thirty minutes. These examples are specifications for implementation, not implemented endpoints. Follow this contract over incompatible layout suggestions in the original product plan.

Review revision R1, October 17, 2026: incorporates the accepted changes from [Ashwin's review](../../REVIEW.md). The [review decisions and owner checklist](REVIEW_UPDATES.md) record what changed and what was deferred. These are agreed implementation requirements, not implemented behavior. Keep the product focused on commitment impact and decision lineage.

**Common rules**

- API prefix: `/api`. JSON property names use snake_case everywhere, including TypeScript response types. Pydantic models live in `backend/app/schemas.py`; Python consumers import those models instead of creating duplicate DTOs.
- All timestamps on the wire are UTC epoch milliseconds. Show dates in `Asia/Kolkata`. Date-only deadlines and delivery forecasts mean the end of their specified IST day. For a live update, `effective_at` is always the server's preview creation time; there is no fixed 6 PM live cutover. Convert dates programmatically. Historical timestamps belong in separate fixtures.
- `evidence_version` is an opaque string composed from a dataset identity and monotonically increasing knowledge revision. Seed/reset creates a new dataset identity. Confirmed knowledge changes increment revision; saving an Action does not. Never parse the version in the frontend.
- Clients send `expected_version` for knowledge confirmation and Action creation. A stale version returns HTTP 409 and requires fresh review. In the MVP, run one API worker and serialise mutations; Ashwin still checks the version inside the graph mutation. Multiple workers are deferred.
- Every query returns explicit completeness metadata. Pagination/traversal bounds or incomplete evidence must never be presented as an exhaustive result.
- Mocks are local development tools. Production graph failures return an error; production AI failures return labelled partial results. Never replace a failed live call with mock success.

**Canonical scenario and IDs**

| Object | ID / fact |
| --- | --- |
| Customers | `cust_acme`, `cust_birch`, `cust_cedar`, `cust_delta` |
| Commitments | `com_acme_sso`, `com_birch_audit`, `com_cedar_export`, `com_delta_sso` |
| Acme path | `wi_sso` → `wi_identity_migration` → `wi_permissions` |
| Birch path | `wi_audit` → `wi_permissions` |
| Cedar path | `wi_export` → `wi_export_worker`, no permissions dependency |
| Delta path | `wi_sso` → `wi_identity_migration` → `wi_permissions` |
| Due dates | Acme October 23; Birch October 26; Cedar October 23; Delta November 5, all 2026 |
| Accepted permissions forecast | October 21 before update; October 28 after update |
| Existing decision | `DEC-12` revises permissions; live note explicitly supersedes it |
| Engineering owners | `person_priya`: permissions; `person_lena`: SSO and identity migration; `person_omar`: audit; `person_eli`: export and export worker |
| Account owners | `person_maya`: Acme; `person_nisha`: Birch; `person_leo`: Cedar; `person_noah`: Delta |
| Required sources | `src_acme_handoff`, `src_birch_handoff`, `src_cedar_handoff`, `src_delta_handoff`, `src_sso_plan`, `src_identity_plan`, `src_audit_plan`, `src_export_plan`, `src_permissions_ticket`, `src_owners`, `src_dec12`, plus source-backed baseline decisions |

All required WorkItems have an accepted baseline forecast before their associated deadlines. This prevents accidental missing-forecast flags on otherwise complete paths. Baseline returns no date conflicts for these four commitments. After the October 28 permissions update, exactly Acme and Birch have date conflicts. Cedar and Delta have no detected date conflict under the recorded model. Separate fixtures cover missing evidence and conflicting facts.

Keep `DEC-12` as its canonical opaque ID; the display string and lookup alias may also be `DEC-12`. Other IDs keep their current values. No naming-style migration is required. The canonical live note is: “Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12.” Delivery dates are not decision-effective timestamps.

Fixtures must include realistic ticket/chat/doc bodies and complete provenance for Cedar/Delta as well as Acme/Birch. Map baseline facts deterministically; do not claim automatic extraction for those mappings. The new pasted decision must use the real extraction/review path. Before recording, also try a valid different delivery date through that path to verify results are not tied to a rehearsed string.

**Forecast provenance and operational graph records**

- Add `Decision -ESTABLISHES-> Forecast`. Each Forecast has exactly one establishing Decision, which has a `SUPPORTED_BY` Source. `decision_id` remains a non-nullable string in blockers/history. Permissions' initial forecast is established by `DEC-12`; every other initial forecast gets an explicit source-backed baseline Decision, for example `dec_baseline_wi_sso`. Do not recover forecast provenance merely by matching every Decision that revises the same WorkItem.
- `GraphState {id:'workspace', dataset_id, revision}` is the singleton version record in the selected demo graph. Confirmed knowledge changes atomically advance it. Reset creates a new dataset identity. Saving an Action leaves the knowledge revision unchanged.
- `RequestRecord {id, dataset_id, operation, idempotency_key, request_hash, result_json, committed_at}` stores completed mutation results. Its identity is scoped by dataset, operation, and key. Persist it in the same version-gated mutation as its Decision/Action. Replaying identical data returns stored success; different data under the same scoped key conflicts. Reset starts a new dataset, so old-dataset requests receive stale-evidence errors rather than replaying into new demo data.
- Expose a selected Decision's source and establishing forecast through the existing history/evidence tools. This supports “Why did this forecast change?” without a new public endpoint or expertise-ranking feature.
- Dependency delays are not automatically copied into downstream WorkItems' forecasts. Always check every recorded dependency along the bounded path. Show the recorded feature forecast alongside the conflicting dependency; describe the discrepancy as requiring replanning, not an automatically recalculated schedule.

**Impact and evidence response**

`GET /api/impacts?as_of=<optional epoch ms>` returns all four commitment summaries, including controls. Without `as_of`, use server time. `available_at`, `due_at`, and `as_of` below are numeric timestamps in real payloads; prose placeholders below explain their meaning.

```typescript
type Completeness = {
  complete: boolean;
  truncated: boolean;
  warnings: string[];
};

type SourceRef = {
  source_id: string;
  quote: string; // exact substring of stored Source.body
};

type PathNode = {
  id: string;
  label: string;
  kind: 'customer' | 'commitment' | 'feature' | 'component' | 'project';
};

type PathEdge = {
  from_id: string;
  to_id: string;
  relation: string;
  source_id: string;
};

type Impact = {
  commitment_id: string;
  customer: { id: string; name: string };
  title: string;
  due_at: number;
  status: 'date_conflict' | 'needs_verification' | 'no_detected_conflict';
  reasons: string[];
  blockers: {
    work_item_id: string;
    name: string;
    forecast_id: string;
    available_at: number;
    decision_id: string;
  }[];
  paths: { nodes: PathNode[]; edges: PathEdge[] }[];
  engineering_owner: { id: string; name: string } | null;
  account_owner: { id: string; name: string } | null;
  citations: SourceRef[];
};

type ImpactResponse = {
  evidence_version: string;
  as_of: number;
  impacts: Impact[];
  completeness: Completeness;
};
```

Paths include customer → commitment → required work item → dependency chain. Edge direction matches graph direction. All edges, including customer/commitment and requirement edges, carry a source_id. Forecast and decision citations accompany blockers. A commitment can have both known blockers and missing information: use `date_conflict` when a confirmed blocker exists and retain the missing-information warning; use `needs_verification` when no confirmed blocker exists but information is incomplete. `no_detected_conflict` requires complete checked evidence for the bounded paths, and UI copy must preserve that limited meaning.

For `date_conflict`, engineering_owner is the unique owner across all blocking WorkItems, not the required feature's owner. If blockers have different owners or any blocker has unresolved ownership, return null plus a warning; do not select the first owner. When there is no confirmed blocker, use the required root WorkItem's unique owner; multiple roots with different/unresolved owners also return null. account_owner comes from the Customer's unique ACCOUNT_OWNER relationship. All demo cases have these explicit owners. Missing/ambiguous engineering or account ownership counts as incomplete information: use `needs_verification` if there is no confirmed date conflict; otherwise retain `date_conflict` with a warning. Expand to owner lists only through an agreed contract update.

`GET /api/sources/{source_id}` returns `{id,type,title,body,source_timestamp,content_hash}`. `GET /api/work-items/{work_item_id}/history` returns `{evidence_version,forecasts:[{id,available_at,valid_from,valid_to,decision_id,citations}]}`. Only accepted forecast facts appear here; interval `valid_to` is nullable.

**Review and confirmation**

1. `POST /api/decisions/preview` accepts `{text, source_title}`. The server supplies source identity and ingestion time. Resolve/extract against known graph IDs. An explicit ambiguous entity should lead to a review message, not a mutation.
2. A valid response contains `{preview_id,evidence_version,expires_at,proposal:{work_item_id,available_at,effective_at,supersedes_id,owner_id,evidence_quote},warnings}`. Store this immutable proposal server-side for fifteen minutes. For the MVP, confirmation is accept/cancel; edits require a fresh preview.
3. `POST /api/decisions/confirm` accepts `{preview_id,expected_version,idempotency_key}`. Look up the immutable proposal, reject expiry/version conflict, and atomically persist its Source, Decision, forecast cutover, provenance, and revised knowledge version. The owner must match the known owner; ownership changes need a separate workflow and are deferred.
4. Return `{decision_id,evidence_version,changed_work_item_ids}`. The frontend then refetches impacts, history, and any selected detail; it invalidates earlier drafts. Replaying the same key and payload returns the original success without another cutover. A reused key with different data returns 409. Check completed replay before rejecting an expired preview or old version.

For every live preview, Pavan supplies `preview_created_at`; set `proposal.effective_at` to that value after extraction. The model cannot choose it. A note explicitly requesting a historical or future decision-effective time returns 422 `review_required`; do not silently override that intent. A future delivery date remains supported. At confirmation, require `current_forecast.valid_from < effective_at <= confirmation_time` and the matching knowledge version. Preview time being a little earlier than confirmation time is valid. A non-forward cutover returns 422 and requires a fresh review. Historical tests use separate seeded intervals, not this live endpoint. Reject unresolved entities or non-approved notes for review. Ambiguous delivery dates require clarification; do not guess a year. Do not treat source text as executable instructions.

**Agent and Action**

`POST /api/agent/run` accepts `{message,commitment_id?,expected_version}`. The expected version protects the user's selected context. It returns:

Required question types: (1) affected promises and accountable owners, and (2) forecast/decision lineage, including “Why did the permissions forecast change?” Both use the same graph, source evidence, and six-call budget. General company Q&A and “who knows the most” ranking are deferred. Generated answers must distinguish a recorded downstream forecast from a conflicting dependency forecast.

```typescript
type Draft = {
  kind: 'internal_escalation' | 'customer_update';
  commitment_id: string;
  assignee_id: string | null;
  body: string;
  citations: SourceRef[];
  based_on_decision_ids: string[];
};

type AgentResponse = {
  run_id: string;
  evidence_version: string;
  status: 'complete' | 'partial';
  answer: string;
  citations: SourceRef[];
  drafts: Draft[];
  tool_trace: {
    tool: string;
    arguments: Record<string, unknown>;
    evidence_ids: string[];
    status: 'ok' | 'error';
  }[];
  warnings: string[];
};
```

Recheck knowledge version before returning a generated draft; if changed, reject with 409. Agent tools retrieve graph facts; they cannot mutate the graph or send messages. Null assignee or insufficient evidence means a draft cannot be saved until the missing information is resolved. An AI failure may return graph facts as a partial answer with empty drafts and explicit warnings.

`POST /api/actions` accepts `{idempotency_key,expected_version,commitment_id,kind,assignee_id,body,citations,based_on_decision_ids}`. Pavan validates the referenced entities, exact source quotes, version, and required fields before Ashwin persists a reviewed Action. Require a nonempty assignee, body, citations, and relevant decision IDs. Reviewed edits are allowed; do not claim that structural citation validation proves every edited sentence. Return `{action_id,status:'reviewed',evidence_version,created_at}`. A saved Action is a persisted draft, not a sent Slack message, ticket, or customer email.

`GET /api/actions?commitment_id=...` returns `{evidence_version,actions:[{id,commitment_id,kind,assignee_id,body,citations,based_on_decision_ids,status,evidence_version,created_at}]}`. Preserve each Action's original evidence_version; if it differs from the current version, the UI marks it for re-review. Actions remain readable after restart.

**Errors and operational endpoints**

All application errors use `{error:{code,message,details}}`; document FastAPI validation errors consistently. Use 409 `stale_evidence`/`idempotency_conflict`, 410 `preview_expired`, 422 `invalid_input`/`review_required`, 503 `graph_unavailable`, and 502 `ai_unavailable` when no useful partial response can be returned. Never include credentials or raw provider exceptions in responses.

`GET /api/health` reports server and graph reachability without needing an LLM call. `POST /api/demo/reset` reseeds only the dedicated synthetic demo graph, creates a fresh dataset identity, and clears pending previews. `POST /api/ingest` imports the documented synthetic fixture format. Pavan decides how reset/ingest are restricted for the hosted demo; neither should accept arbitrary graph names from the browser. Seed/reseed is a controlled demonstration operation, not a general company upload feature.

**Python module handoffs**

Ashwin exposes a synchronous `GraphRepository` in `backend/app/graph/repository.py`. Its service methods accept validated Python values and return primitives/DTOs, not raw FalkorDB Node/Path objects:

```text
get_version()
seed_demo(fixtures_dir)
list_impacts(as_of)
get_source(source_id)
get_history(work_item_id)
resolve_entity(query, kind)
get_owners(commitment_id)
get_evidence(commitment_id, as_of)
confirm_decision(proposal, source, expected_version, idempotency_key)
save_action(action, expected_version, idempotency_key)
list_actions(commitment_id)
```

Agree exact Python signatures and DTOs with Pavan at kickoff; the wire contract above stays authoritative. Keep synchronous graph calls off the async event loop using a threadpool or FastAPI's synchronous handlers. Use typed errors that Pavan maps into the HTTP contract. Persistent idempotency records live in FalkorDB; request-time preview data may remain in memory and expires on restart.

Before the first parallel work handoff, Pavan and Ashwin publish the exact typed repository signatures and Pavan's Pydantic models, plus one real JSON example each for baseline/changed impacts, history, preview/confirm, agent complete/partial, saved Actions, and 409/410 errors. Consumers may start layout/provider scaffolding before that handoff, but must not invent competing field definitions. This is the kickoff deliverable, not an additional feature phase.

Abhijeet exposes async `extract_decision(text, candidates, source_id, now)` in `backend/app/ai/extraction.py` and `run_agent(request, tools)` in `backend/app/ai/agent.py`. Extraction never writes; provider setup never makes network calls at module import. Pavan owns preview storage and source/decision confirmation. Tools expose only read operations over Ashwin's repository plus pure drafting; no circular imports between API, graph, and AI packages.
