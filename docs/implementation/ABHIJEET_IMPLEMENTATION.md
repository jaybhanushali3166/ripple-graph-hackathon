# Abhijeet — extraction, agent tools, and grounded drafting

You own the AI layer. It turns a new engineering note into a reviewed proposal, uses graph tools to investigate impact, and prepares useful follow-up drafts. Ashwin's queries determine facts; your model explains and drafts from them. You do not own graph writes or API route orchestration.

Read the [team sequence](../../TEAM_IMPLEMENTATION_PLAN.md) and [shared contract](SHARED_CONTRACT.md). Branch: `feat/abhijeet-agent`.

**Files you own**

```text
backend/app/ai/__init__.py
backend/app/ai/provider.py
backend/app/ai/extraction.py
backend/app/ai/agent.py
backend/app/ai/tools.py
backend/app/ai/grounding.py
backend/app/ai/prompts/*
tests/ai/*
docs/ai-assistance.md
docs/agent-grounding.md
```

Request Python SDK/dependency changes from Pavan. Import shared DTOs from his schemas module. Keep provider initialization lazy; importing your package must not require a secret or make a network request. Graph tools depend on an injected repository interface, not FastAPI routes.

**First thirty minutes**

Confirm the team has access to one suitable model account. Run a small structured-output and tool-call smoke check, then report model/configuration/dependency needs to Pavan. Use environment settings and never put keys in source. Agree input/output models and an async interface for extraction and agent execution. Start with provided fixture examples rather than waiting for Ashwin's complete implementation.

**Hours 0:30–2:00: extraction and provider boundary**

Implement `extract_decision(text, candidates, source_id, now)`. It returns a typed proposal with known work_item_id, available_at, effective_at, supersedes_id, owner_id, and an exact evidence_quote. Source identity/time come from the server, not model invention. Use the shared date convention and explicit 2026 fixture context.

The canonical note should resolve the permissions service, October 28 delivery, Priya, and DEC-12. Reject or request review for missing/ambiguous year, unknown entity, conflicting dates, or an ownership reassignment. The model may propose candidates; server validation establishes whether IDs and quotations are legitimate. Never confirm or persist from extraction.

Implement provider timeout and schema-error handling. Test against valid notes, contradictory notes, unknown names, and source text containing instructions to ignore the system. A deterministic test double is useful for development; it must never silently replace failed live AI in the shipped workflow.

**Hours 2:00–4:00: tools and the bounded agent**

Implement these operations using Ashwin's repository:

- `resolve_entity`: find candidates; preserve ambiguity.
- `find_impacted_commitments`: retrieve actual statuses, blockers, version, and completeness.
- `get_evidence`: retrieve ordered proof paths and source quotes.
- `get_owners`: retrieve accountable people without guessing.
- `get_forecast_history`: compare accepted forecast versions.
- `draft_followup`: a pure drafting step grounded in retrieved facts.

Use at most six tool calls, with a total deadline agreed with Pavan. Questions about a selected commitment should not require a separate lookup for every field if evidence is already present. The tool interface may bundle related read data to keep a genuine tool-calling flow within the budget. Do not pre-script Acme's answer or route to fixture expected results.

Expose `run_agent(request, tools)` returning the agreed AgentResponse. Log tool names, parameters, evidence IDs, and success/error only. Do not expose private chain-of-thought. A tool timeout or completeness warning leads to a partial result or explicit verification request.

Handoff by hour four: Pavan can call your agent with real repository tools and receive cited facts in the agreed schema.

**Hours 4:00–6:00: explain and draft**

Provide one clear explanation of how the revised permissions forecast crosses the selected promise deadline, citing each relevant source. Supply an internal escalation for the engineering owner and a customer-update draft for the account owner.

Customer text must not invent a replacement delivery date, claim a breach has already occurred, or describe synthetic contract value as actual loss. If no owner/evidence exists, return a warning and do not produce a saveable draft. The decision date and promised date are distinct facts; do not swap them.

Validate model-returned IDs, date/value fields, source references, and exact quotes against tool evidence. Prefer templated rendering for critical factual claims and let the model handle connective language. Do not claim simple citation validation proves unrestricted free-text correctness. Unsupported claims require regeneration or a labelled factual fallback with empty drafts.

Pavan rechecks evidence_version before returning results; pass through the version your tools used. Jay invalidates drafts when knowledge changes. Pair with them on both paths.

**Hours 6:00–8:00: meaningful checks**

- New permissions note extracts correctly without hardcoded customer names.
- Unknown names and ambiguous dates yield review, not guessed graph IDs.
- Source instructions cannot trigger sending, arbitrary queries, or writes.
- The Acme explanation cites the promise, dependency, and revised forecast correctly.
- An unrelated-customer question stays consistent with graph controls.
- Missing owner/evidence and conflicted forecasts produce explicit limitations.
- Provider timeout/schema failure yields labelled failure/partial output.
- The agent respects six calls and returns useful evidence when it stops.
- Unsupported date/owner/source in model output is rejected.
- A newer knowledge revision prevents old drafts being presented as current.

Keep deterministic unit checks separate from actual provider smoke checks. Record which checks used a test double and which exercised the real model. Do not report invented accuracy percentages.

**Hours 8:00–10:00: judging evidence**

Write `docs/agent-grounding.md` describing tools, prompts, validation limits, budgets, actual checks, and fallback behavior. Write `docs/ai-assistance.md` with each person's truthful AI usage and verification contribution; ask the team to supply their own details. Give Jay one reliable sample question and one limitation case for recording, and give Pavan the final environment/configuration list.

Your definition of done: a genuine bounded tool-calling run uses live graph evidence, a freshly pasted note passes review extraction, drafts remain accountable and sourced, and failures are explicit. No real message is sent to Slack, customers, or teammates.
