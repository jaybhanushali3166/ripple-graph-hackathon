# Pavan — API, workflow services, infrastructure, and integration

You own the boundary that makes the four workstreams one product. Publish stable schemas first, connect Ashwin's graph and Abhijeet's AI modules, and give Jay a working API early. You coordinate integration and setup; the other owners remain responsible for defects in their modules.

Read the [team sequence](../../TEAM_IMPLEMENTATION_PLAN.md) and [shared contract](SHARED_CONTRACT.md). Branch: `feat/pavan-api`.

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

Agree shared Pydantic models and graph/AI signatures. Publish request/response examples matching the shared contract, including errors, completeness, nullable owners, and opaque evidence_version. Ask Jay to mirror these fields in TypeScript. Choose backend/frontend ports and a local Vite proxy so everyone uses `/api` without guessing origins.

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

Implement preview with Abhijeet's extractor: resolve candidates through Ashwin, validate typed fields and exact evidence quotes, and store an immutable proposal with a fifteen-minute expiry and current version. Matching a known owner is validation; do not introduce ownership reassignment.

Implement confirm: check completed idempotency replay first, validate preview/version/effective time, then call Ashwin's atomic mutation. Never trust proposal fields resent by the browser. Return the new evidence version and changed IDs so Jay refetches rather than locally inventing impacts.

Wire `/agent/run` to Abhijeet's agent and repository-backed read tools. Enforce current context at start and recheck version before returning drafts. Complete expected model timeouts and useful partial-result behavior with Abhijeet.

Implement Action creation/listing. Validate current version, commitment/assignee existence, exact cited text, relevant decision IDs, and required fields; delegate persistence/idempotency to Ashwin. A reviewed Action is a stored draft, never an external send.

**Hours 6:00–8:00: integration and failures**

Coordinate a full browser walkthrough with the team: reset → baseline → preview → confirm → changed impacts → source/history → agent → edit draft → save → refresh/restart → saved Action. Each owner fixes their own layer.

Verify stale preview/action requests return 409; expired previews return 410; duplicate requests replay cleanly; invalid inputs cause no partial mutation; unknown sources are handled clearly. Confirm a newer decision invalidates an old agent draft. Verify graph failure is honest and AI failure is labelled partial or unavailable. Run at least one simultaneous-confirmation check against the real database.

Unify error envelopes, including request validation. Keep secrets out of responses and checked-in files. Reset/reseed is an intentional test operation; test only the dedicated synthetic graph.

**Hours 8:00–10:00: reproducibility and submission**

Finish a clean-checkout README with environment names, dependency installation, startup, seed/reset, verification, data model/query links, and known limits. Ask a teammate who did not write setup to run it. Assemble measured verification results from all owners in `docs/verification.md`. Add minimal CI for the meaningful checks that are ready; CI expansion must not block the working demo.

If deployment still consumes more than forty-five additional minutes without progress, finish complete local instructions and the demo recording instead. Coordinate final repository/deployment/video links and submit with Jay before the buffer ends.

Your definition of done: the UI, agent, and graph speak the same contract; a fresh checkout reproduces the story; mutation/replay/version behavior is correct; the submission is complete and accessible.
