# Pavan — API, workflow services, infrastructure, and integration

You own the boundary that makes the four workstreams one product. Publish stable schemas first, connect Ashwin's graph and Abhijeet's AI modules, and give Jay a working API early. You coordinate integration and setup; the other owners remain responsible for defects in their modules.

Read the [team sequence](../../TEAM_IMPLEMENTATION_PLAN.md) and [shared contract](SHARED_CONTRACT.md). Branch: `feat/pavan-api`.

**Review revision R1 — apply before integration**

- Publish exact Pydantic models, typed graph/AI interfaces with Ashwin/Abhijeet, and example JSON for baseline/changed impacts, history, preview/confirm, agent complete/partial, Actions, and 409/410 errors during kickoff. This unblocks parallel consumers.
- Preserve non-nullable decision_id: Ashwin supplies one establishing Decision per Forecast, including source-backed baselines. Keep `DEC-12`; no ID-style migration.
- Assign live effective_at from server preview creation time after extraction. Reject explicit custom historical/future decision-effective times with 422 review_required. A future delivery date remains valid. Confirm against the stored preview and active interval, not a comparison that rejects every time earlier than now.
- Follow R1 engineering-owner selection and missing-owner status precedence; do not replace a component owner with the feature owner or select the first of several people.
- Verify GraphState/RequestRecord persistence, full Cedar/Delta provenance, and reset dataset semantics with Ashwin. Keep basic stale/expiry/replay behavior and one overlapping-confirmation check.
- Integrate two bounded question types: impact/owners and decision lineage. Document recorded downstream forecasts versus conflicting dependencies; no automatic schedule recalculation.
- Defer broad CI, expertise ranking, additional seed-extraction pipelines, and side-prize work until the working submission is verified.

See the [review disposition](REVIEW_UPDATES.md); integration ownership and time gates remain unchanged.

**Files you own**

```text
backend/app/__init__.py
backend/app/main.py
backend/app/settings.py
backend/app/schemas.py
backend/app/api/*
backend/app/services/*
backend/pyproject.toml and backend lockfile
backend/Dockerfile
docker-compose.yml
.env.example
.gitignore
.github/workflows/*
tests/api/*
tests/integration/*
README.md
docs/verification.md
docs/implementation/SHARED_CONTRACT.md
```

Jay owns frontend manifests and Dockerfile if needed. Ashwin owns graph imports/mutations and fixtures. Abhijeet owns provider, extraction, and agent code. Agree their dependency needs in kickoff; you make backend manifest/lockfile changes centrally.

**First thirty minutes**

Agree and publish shared Pydantic models and exact typed graph/AI signatures under R1. Publish the example payload set listed above, including baseline establishing decisions, component-owner choice, review timestamps, errors, completeness, nullable owners, and opaque evidence_version. Ask Jay to mirror these fields in TypeScript. Choose backend/frontend ports and a local Vite proxy so everyone uses `/api` without guessing origins.

Keep one API worker for this deadline. Mutating services use a shared lock; atomic version predicates remain inside Ashwin's graph writes. Preview storage may be process-local with an expiry; persistent facts and idempotency records live in FalkorDB.

**Hours 0:30–2:00: scaffolding and contract delivery**

1. Scaffold FastAPI, settings, error mapping, schemas, and explicit development response examples. Keep mocks in test/dev support and make their mode visible.
2. Compose the database and backend; coordinate the frontend service with Jay. Use an internal database connection and a persistent volume. Pin the working database image and dependencies after a real smoke check.
3. Expose `/api/health`, document local startup, and verify another teammate can run it.
4. Define route/service files for impacts, sources/history, ingestion/reset, preview/confirm, agent runs, and Actions.
5. Hand Jay exact base URL, response examples, and which routes are already real. Give Abhijeet a test invocation of his async entry points.

Do not wait for all graph methods before building routes; dependency injection and explicit test doubles should unblock your work.

**Hours 2:00–4:00: connect the real graph**

Wire real `/impacts`, `/sources/{id}`, and `/work-items/{id}/history` routes to Ashwin's repository. Serialize graph paths into the agreed nodes/edges; return no raw client objects. Keep blocking graph calls off the async event loop.

Implement deterministic fixture ingestion and controlled demo reset using Ashwin's seed methods. Reset clears pending previews and establishes a new evidence identity. Reject arbitrary browser-supplied graph names. Scope reset/import to the synthetic demo; choose a simple deliberate operator mechanism for a hosted instance and document it.

Probe hosting now: confirm the chosen host can run the backend and reach persistent FalkorDB. Do not spend the whole window on deployment. The hour-four gate is Jay's browser displaying real graph data.

**Hours 4:00–6:00: workflow orchestration**

Implement preview with Abhijeet's extractor: resolve candidates through Ashwin, validate typed fields and exact evidence quotes, then assign effective_at from the server's preview_created_at and store the immutable proposal with a fifteen-minute expiry and current version. Custom historical/future decision-effective requests require review instead of silently overriding their intent. Delivery dates may be future dates. Matching a known owner is validation; do not introduce ownership reassignment.

Implement confirm: check completed idempotency replay first, validate preview/version and `current_forecast.valid_from < preview_created_at <= confirmation_time`, then call Ashwin's atomic mutation. Never trust proposal fields resent by the browser or reject a valid preview just because its time precedes confirmation. Return the new evidence version and changed IDs so Jay refetches rather than locally inventing impacts.

Wire `/agent/run` to Abhijeet's agent and repository-backed read tools for impact/owners and decision lineage. Enforce current context at start and recheck version before returning drafts. Complete expected model timeouts and useful partial-result behavior with Abhijeet. Lineage uses establishing Decisions and source evidence through existing history/evidence tools; no extra public endpoint is required.

Implement Action creation/listing. Validate current version, commitment/assignee existence, exact cited text, relevant decision IDs, and required fields; delegate persistence/idempotency to Ashwin. A reviewed Action is a stored draft, never an external send.

**Hours 6:00–8:00: integration and failures**

Coordinate a full browser walkthrough with the team: reset → baseline → preview → confirm → changed impacts → source/history → agent → edit draft → save → refresh/restart → saved Action. Each owner fixes their own layer.

Verify stale preview/action requests return 409; expired previews return 410; duplicate requests replay cleanly; invalid inputs cause no partial mutation; unknown sources are handled clearly. Confirm a newer decision invalidates an old agent draft. Verify graph failure is honest and AI failure is labelled partial or unavailable. Run at least one simultaneous-confirmation check against the real database.

Also verify immediate post-confirmation impacts without a fixed clock-time dependency, a different valid delivery date, complete control-customer sources, non-null baseline lineage, and component-owner/null-warning behavior. Keep these checks before optional CI expansion or blog work.

Unify error envelopes, including request validation. Keep secrets out of responses and checked-in files. Reset/reseed is an intentional test operation; test only the dedicated synthetic graph.

**Hours 8:00–10:00: reproducibility and submission**

Finish a clean-checkout README with environment names, dependency installation, startup, seed/reset, verification, data model/query links, and known limits, including deterministic seed mappings, server-timed live updates, and no automatic downstream replanning. Ask a teammate who did not write setup to run it. Assemble measured verification results from all owners in `docs/verification.md`. Minimal existing checks may run in CI; CI expansion must not displace core verification or the working demo.

If deployment still consumes more than forty-five additional minutes without progress, finish complete local instructions and the demo recording instead. Coordinate final repository/deployment/video links and submit with Jay before the buffer ends.

Your definition of done: the UI, agent, and graph speak the same contract; a fresh checkout reproduces the story; mutation/replay/version behavior is correct; the submission is complete and accessible.
