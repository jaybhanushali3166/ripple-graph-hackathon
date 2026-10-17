# Ripple — plan review

Reviewed October 17, 2026, by Ashwin (with AI assistance). This reviews [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [TEAM_IMPLEMENTATION_PLAN.md](TEAM_IMPLEMENTATION_PLAN.md), [SHARED_CONTRACT.md](docs/implementation/SHARED_CONTRACT.md), and the four individual implementation files. It compares them against the [event page](https://www.wemakedevs.org/hackathons/falkordb) and [rules](https://www.wemakedevs.org/hackathons/falkordb/rules). No application code exists yet.

Plan follow-up: see [accepted review changes, revision R1](docs/implementation/REVIEW_UPDATES.md). The observations below describe the earlier plan; the linked disposition identifies the changes now incorporated and the optional suggestions deferred.

## 1. Verdict

The plan fits Track 3 (Company Brain), and its central bet is right: a live change, a clickable evidence chain from that change to the affected customers, and unaffected control customers. That matches the track's emphasis on current knowledge with sources.

It has two main risks:

1. **It may look narrow and hand-wired** next to the track's "build an agent that understands how a company works."
2. **It spends hours on correctness that judges won't see**, with the deadline about 30 hours away.

Neither the event page nor the rules publish a scoring rubric. The assessment below uses the Track 3 description and the general challenge wording.

## 2. Coverage of the Track 3 focus areas

| Track 3 asks for | Current plan | Assessment |
| --- | --- | --- |
| Tracing decisions back to their source | Decisions link to their source documents, DEC-12 is superseded by the new note, and citations are exact quotes shown in a source drawer | **Strong**, the plan's best part |
| Keeping knowledge current as things change | Forecast history, the live note changes the results, versioning, and old drafts get flagged for re-review | **Strong**, and the demo's central moment |
| Answers with clear sources | Claims are checked against stored sources, with a clickable evidence path | **Strong** |
| Who owns what **and who knows what** | Engineering and account owners are covered; nothing models who knows what | **Partial gap** |
| Knowledge from docs, tickets and chats in one graph | About 20 hand-written synthetic records with the relationships pre-mapped; only the pasted note goes through extraction | **Weak spot**: can look hand-wired rather than understood |

The challenge says "the graph has to shape what the agent does, not sit on the side." The plan meets this: a graph query decides which customers are affected. The edge-removal check (remove a dependency, the flag disappears; restore it, the flag returns) proves it. **Show that check in the demo video**, because it directly answers the rule that "a visualisation drawn on top of ordinary storage does not qualify."

## 3. Rules compliance

| Requirement | Status in the plan |
| --- | --- |
| FalkorDB is the primary graph database and central to the product | Yes |
| Public, synthetic, or own data only | Yes, all Harbor data is synthetic |
| Public source repository | Planned |
| README with setup instructions and the graph data model | Planned (README plus `docs/graph-model.md`; the README should include or link the model) |
| Cypher queries or graph algorithms the product depends on | Planned (`backend/queries/*.cypher`) |
| Demo video of the working project | Planned (Jay) |
| Live deployment, or complete local setup | Planned, with local setup as the fallback |
| Declared track(s) | Track 3; see section 5 |
| AI-assistance disclosure | Planned (`docs/ai-assistance.md`) |

**Cleanup needed before the repo goes public:**

- `IMPLEMENTATION_PLAN.md` line 253 contains a teammate's local machine path (`/Users/jaybhanushali/.codex/...`) and some notes about Codex plugins. Remove them.
- `TEAM_IMPLEMENTATION_PLAN.md` labels Jay as "you" in the ownership table, so it reads as if written from Jay's point of view. Make it neutral.

## 4. Recommended changes

### 4.1 Add "who knows what" (small, graph-side)

Add a `Person -AUTHORED-> Source` edge, plus a few chat or meeting sources where people discuss work items. Then the agent can answer "Who knows the most about the permissions service?" by walking from people to sources to work items. This takes one query and one fixture change, and it closes the visible gap.

### 4.2 Make the incoming data look less hand-wired

- Write the fixtures as realistic tickets, chat threads and docs (stored as Source nodes), not only structured JSON.
- Have the agent answer at least one question by drawing on several of these sources.
- If time allows, run one or two fixture documents through the same extraction at seed time. Then "the graph was built from documents" is true for more than the single pasted note.

### 4.3 Present it as a company brain, not a single-purpose tool

Pitch it as: "Harbor's people, teams, projects, documents and decisions in one graph. The standout question is which customer promises break when engineering changes a date." Then show one or two other questions answered from the same graph, such as decision lineage ("why is the permissions date October 28?") or who to ask. The team plan currently cuts "arbitrary questions" first if time runs short. Keep **two pre-tested question types** instead.

### 4.4 Cut correctness work judges won't see

Judges mostly see a three-minute video and the repository.

- **Keep:** the version check inside the graph write, duplicate-save protection for Actions and decisions, and honest completeness warnings. These are cheap and visible in the code.
- **Cut or defer before cutting 4.1–4.3:** the simultaneous-confirmation test, preview expiry (HTTP 410) handling, CI, and the more detailed stale-draft UI states.

### 4.5 Free extras

- **Multiple tracks:** the rules allow entering more than one. Declaring Track 1 as well costs nothing, since the agent acts on what the graph shows. Don't build for it: Track 1 emphasizes MCP tool selection and graph algorithms.
- **Blog side prize** (AirPods, one winner): `docs/graph-model.md` is most of a blog post already. Write it during the buffer hours.

## 5. Contract gaps to settle at kickoff

Each of these is unspecified or inconsistent in the shared contract, and each lands in the graph layer.

1. **Nothing links a forecast to its decision.** `blockers[].decision_id` is non-nullable and the history endpoint returns a `decision_id` per forecast, but the graph contract only has `Decision -REVISES-> WorkItem`. Add `Decision -ESTABLISHES-> Forecast`, or a `decision_id` property on Forecast. Baseline forecasts for `wi_sso`, `wi_export` and the others have no decision behind them: either seed one for each, or make `decision_id` nullable.
2. **Two node types are missing from the graph contract:** one holding the version (dataset ID plus revision number) and one recording duplicate-request (idempotency) keys. Document both in `docs/graph-model.md`.
3. **The decision ID format doesn't match.** `DEC-12` breaks the prefixed snake_case style (`cust_`, `wi_`, `src_`). Proposal: ID `dec_12`, display name `DEC-12`, and an entity-lookup alias that maps "DEC-12" to it.
4. **Cedar and Delta have no source records.** Every proof-bearing edge needs a `source_id`, but the core source list has no Cedar or Delta handoff and no export plan. Add `src_cedar_handoff`, `src_delta_handoff` and `src_export_plan`.
5. **"Engineering owner" is ambiguous.** For Acme, it could be the owner of the work item causing the conflict (Priya, permissions) or of the feature Acme requires (`wi_sso`). Proposal: the conflicting item's owner when there is a conflict, otherwise the required feature's owner. Name the `wi_sso` owner in the fixtures.
6. **"Backdated" is undefined.** `effective_at` defaults to preview creation time, so it is always a little before confirmation. Proposal: backdated means earlier than the start date of the forecast currently in effect, not earlier than now.
7. **It's unclear whether a missing owner changes the status.** Section 7 of the original plan says absent ownership means "needs verification", but the contract's status rule only mentions blockers and incomplete information. Proposal: a missing owner counts as incomplete information, giving `needs_verification` (or `date_conflict` plus a warning when there is also a conflict).
8. **Delays don't carry down the dependency chain.** After the update, `wi_sso` keeps its own October 22 forecast even though it depends on a component now due October 28. Acme is still flagged, because the query checks every item along the chain. Document the stale downstream forecast as a known limitation in the README.

## 6. Graph implementation notes

- **Single-write atomicity.** FalkorDB runs each write query on its own. One Cypher statement that matches the version node with `revision = $expected` and chains every later write with `WITH` creates nothing when the version is stale. Check for a repeated request key first (a read under Pavan's lock), then do the version-gated write. This also covers two overlapping confirmations.
- **Date convention.** Store deadlines and forecasts as the next IST midnight minus 1 ms, and compare with strict `>`. A forecast on the same day as the deadline is then not a conflict.
- **Query details to confirm against the pinned FalkorDB image:** support for `[:DEPENDS_ON*0..4]`, returning properties via `nodes(p)` and `relationships(p)` instead of path objects, and using `ro_query` for every read.
- **Depth limit and cycles.** Report truncation honestly by running a separate existence check for paths five hops deep. Catch cycles when the data is imported.
- **Requirements to hand Pavan:** a pinned `falkordb/falkordb` image tag, the persistent volume path (confirm it for that image), the environment variables `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_PASSWORD` and `RIPPLE_GRAPH_NAME`, and a separate graph name for tests.

## 7. Schedule

It is October 17. Submissions close October 18 at 11:59 PM IST, and the plan freezes features at 8:00 PM IST that day. Settle section 5 in the first thirty minutes, because Pavan's DTOs and Jay's TypeScript types depend on those fields. Fold 4.1 and 4.2 into the fixtures and queries from the start rather than adding them later.
