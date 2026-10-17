# Ashwin — graph, fixtures, and domain correctness

Your responsibility is to make FalkorDB determine the answer. You own source-backed relationships, impact detection, accepted forecast history, graph mutations, and durable Actions. Pavan consumes your repository; Abhijeet consumes its read operations through tools; Jay consumes the API responses.

Read the [team sequence](../../TEAM_IMPLEMENTATION_PLAN.md) and [shared contract](SHARED_CONTRACT.md). Branch: `feat/ashwin-graph`.

**Files you own**

```text
backend/app/graph/__init__.py
backend/app/graph/client.py
backend/app/graph/repository.py
backend/app/graph/errors.py
backend/queries/*.cypher
fixtures/harbor/sources/*
fixtures/harbor/entities/*
fixtures/harbor/decisions/*
fixtures/harbor/expected/*
tests/graph/*
docs/graph-model.md
```

Pavan owns wire schemas, environment configuration, dependencies, and Docker Compose. Give him database/image/persistence requirements during kickoff. Do not edit those files in parallel. You may add domain helpers beneath your graph directory.

**First thirty minutes**

Confirm canonical IDs/dates, forecast interval semantics, graph method signatures, and exception names with Pavan. Give Abhijeet sample lookup and evidence results; give Jay sample path nodes/edges through the shared contract. Freeze the initial four-customer story before adding peripheral entities.

**Hours 0:30–2:00: fixtures and real reads**

1. Connect the official client using Pavan's settings; select a server-configured demo graph. Keep database access in this package.
2. Seed the canonical customers, commitments, work items, people, teams, decisions, and Source bodies. Every proof-bearing edge gets a source_id. Use stable IDs and deterministic import keys.
3. Give every required work item an accepted baseline forecast so no unrelated missing-data warning spoils the main story. Add separate negative fixtures later.
4. Implement `get_version`, `list_impacts`, `get_source`, `get_owners`, `get_evidence`, and `resolve_entity`. Return serialization-friendly values with source quotes and the full ordered evidence path.
5. Deliver a CLI/smoke command showing the baseline's four statuses and source retrieval. Tell Pavan the exact command and inputs.

Current impacts must be computed from FalkorDB. Fixture expected outputs are test assertions, not a runtime lookup table. Use parameterized read-only queries for retrieval. Graph outages raise a typed error.

**Hours 2:00–4:00: accepted updates and history**

Implement `confirm_decision` with an atomic knowledge-version check, old forecast closure, new forecast, Source and Decision links, and durable idempotency result. A completed same-key replay returns its original result; different payload under that key conflicts. Keep old accepted forecasts for historical queries. An absent old forecast, unknown target, invalid owner, backdated effective time, or conflict must not partially mutate the graph.

Use one graph statement for the cutover where practical; verify the version predicate gates every mutation, not only the first match. Pavan serialises service mutations in the single-worker API, but correctness still belongs in the graph write. Store a dataset identity plus revision on a graph state node. Coordinate seed/reset with Pavan so stale clients cannot match a freshly reset revision.

Implement history and missing/conflicting evidence queries. Classify a confirmed late dependency as a date conflict, preserve warnings, and distinguish incomplete evidence from no detected conflict. Bound dependency expansion at four hops and detect cycles/deeper paths so completeness metadata is truthful. Deduplicate commitments while retaining multiple proof paths.

Handoff by hour four: repository works against the real graph; Pavan can confirm the canonical decision and read exact affected IDs without AI.

**Hours 4:00–6:00: durable Actions and integration**

Implement `save_action` and `list_actions`: persist reviewed text, assignee, citations, relevant Decision links, evidence_version, creation time, and an idempotency record. Confirm the expected knowledge version before creating an Action; Action saves do not increment that version. Return prior success on an identical replay even after later knowledge changes.

Support source/ID checks required by Pavan's services. Expose enough provenance to validate citations and based-on decision IDs. Pair with Pavan on the live confirm endpoint and Abhijeet on tool evidence. Help Jay only through concrete API/path examples rather than frontend edits.

**Hours 6:00–8:00: verification**

Your release checklist:

- Baseline: no date conflicts for the four canonical commitments.
- October 28 update: exactly `com_acme_sso` and `com_birch_audit` flagged; Cedar and Delta remain controls.
- Before/after effective time returns the appropriate accepted forecast.
- Missing forecast, conflicting evidence, missing owner, cycle, and deeper-than-limit cases expose verification warnings.
- Removing a relevant dependency changes reachability and its derived flag; restoring it restores the expected result.
- Duplicate source/decision/action requests do not duplicate graph facts.
- Stale version and invalid mutation leave graph state unchanged.
- Two overlapping confirmation attempts cannot both replace the same revision.
- Restart preserves forecasts, sources, and Actions.

Use the actual pinned FalkorDB instance for query checks. Record observed results and query timings; do not describe targets as achieved benchmarks.

**Hours 8:00–10:00: handoff for judging**

Write `docs/graph-model.md`: labels/edges, one full evidence path, central Cypher, time/version semantics, seed/reset command, bounds, and known limitations. Give Pavan a concise graph test result and help rehearse explaining why the graph is essential.

Your definition of done: another developer can seed, apply the new decision, retrieve exact changed commitments and citations, restart, and retrieve the reviewed Action. No AI or frontend is necessary to verify your graph semantics.
