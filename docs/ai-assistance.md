# AI Assistance & Verification Disclosure

This document records the truthful AI assistance used during the development of Ripple, alongside the manual verification, architectural review, and engineering contributions of each team member.

Per team plan guidelines, each developer supplies their own truthful AI usage and verification details below.

---

## 1. Team Contributions & AI Usage Disclosure

| Developer | Role & Owned Scope | AI Assistance Tools Used | Human Verification & Engineering Contribution |
| --- | --- | --- | --- |
| **Abhijeet Pandhe** | AI layer: Decision extraction, bounded agent, tool suite, grounding validator, and test suites | Antigravity AI pair programming assistant (Gemini 3.8 Flash) | Authored provider boundary, prompt templates, candidate resolution logic, exact substring quotation verifier, 6-call budget limiter, customer draft safety guardrails, and deterministic unit/integration test suites. Verified zero-leakage of chain-of-thought, server-owned `effective_at` enforcement, and prompt injection resilience. |
| **Ashwin** | Graph layer: FalkorDB schema, Cypher queries, `GraphRepository`, atomic writes, and Harbor fixtures | *[To be supplied by Ashwin]* | *[To be supplied by Ashwin]* |
| **Pavan** | API & Integration: FastAPI routing, Pydantic v2 wire models, infrastructure, Docker, and CI | *[To be supplied by Pavan]* | *[To be supplied by Pavan]* |
| **Jay** | Frontend: UI layout, evidence-path graph visualization, decision review flow, action editor | *[To be supplied by Jay]* | *[To be supplied by Jay]* |

---

## 2. Handoff Data for Demo Recording (Jay)

To assist Jay in recording the demo video, here are the verified query scenarios and limitation cases:

### Scenario A: Impact & Accountable Owners
- **Input Query**: *"What commitments are impacted by the permissions delivery update to October 28?"*
- **Context**: Select `com_acme_sso` (Acme Corp).
- **Expected Graph Facts**:
  - `com_acme_sso` has status `date_conflict` because `wi_permissions` (delivery October 28, 2026) is after Acme's due date (October 23, 2026).
  - Accountable engineering owner: **Priya Sharma** (`person_priya`), who owns the blocking component `wi_permissions`.
  - Account owner: **Maya Patel** (`person_maya`), who is the account executive for Acme.
  - Generates two grounded drafts citing the commitment promise, dependency, and revised forecast:
    1. Internal escalation to Priya Sharma.
    2. Customer update to Maya Patel.
  - Explains that downstream SSO feature schedule has not been automatically recalculated and requires replanning.

### Scenario B: Forecast & Decision Lineage
- **Input Query**: *"Why did the permissions forecast change from DEC-12?"*
- **Expected Graph Facts**:
  - Initial forecast was established by `DEC-12` (delivery October 21, 2026), citing `src_dec12`.
  - Revised forecast is established by `dec_live_permissions_001` (delivery October 28, 2026), explicitly superseding `DEC-12`, citing `src_permissions_ticket`.
  - Answers that provenance is strictly grounded in the approved ticket update, citing exact dates (Oct 21 -> Oct 28), without guessing unrecorded corporate rationales.

### Scenario C: Limitation & Rejection Case
- **Input Query / Note**:
  - *Option 1 (Retroactive Effective Time)*: `"Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This decision is effective retroactively from October 1."`
  - *Expected Outcome*: Returns HTTP 422 with `reason: "custom_effective_time_unsupported"`. Demonstrates that server preview creation time must be used and retroactive backdating is halted for review.
  - *Option 2 (Ambiguous Year)*: `"Approved: permissions service delivery moves to October 28. Owner: Priya."`
  - *Expected Outcome*: Returns HTTP 422 with `reason: "missing_or_ambiguous_year"`. Demonstrates strict refusal to guess calendar years.

---

## 3. Environment & Configuration Manifest (Pavan)

Configuration variables required by the AI layer:

```bash
# LLM Provider Configuration (Ollama Cloud)
# When set, the system uses live Ollama Cloud LLM calls with native function calling.
# API keys are passed strictly via the 'Authorization: Bearer <token>' HTTP header.
LLM_API_KEY=your-ollama-api-key-here
LLM_MODEL=llama3.3
LLM_BASE_URL=https://ollama.com

# Development & Test Mode
# When false, live Ollama API is invoked.
# When true, deterministic test doubles can be used during local offline development.
DEV_MOCKS=false
```
