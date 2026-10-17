# Ripple Agent Grounding & AI Architecture

Author: Abhijeet Pandhe (AI Layer Owner)  
Scope: Extraction, bounded agent tools, grounding verification, and follow-up drafting.

---

## 1. Architectural Boundary & Guiding Principles

The Ripple AI layer operates strictly as an explanation and drafting assistant over graph truth.
Ashwin's FalkorDB queries determine facts; the AI layer explains and drafts from them.

```
       +-------------------------------------------------------------+
       |                     User / Frontend                         |
       +------------------------------+------------------------------+
                                      |
                      POST /api/decisions/preview
                      POST /api/agent/run
                                      |
       +------------------------------v------------------------------+
       |                       FastAPI Layer                         |
       |  (Pavan: assigns preview_created_at, checks expected_ver)   |
       +--------------+------------------------------+---------------+
                      |                              |
       +--------------v---------------+  +----------v---------------+
       |       Extraction Engine      |  |     Bounded AI Agent      |
       |  (extract_decision, review)  |  |   (genuine tool loop)     |
       +--------------+---------------+  +----------+---------------+
                      |                              |
                      | Candidates                   | Tool invocations
                      |                              | (up to 6 calls)
       +--------------v------------------------------v---------------+
       |                      AgentTools                             |
       |       (resolve_entity, find_impacted, get_evidence,         |
       |        get_owners, get_forecast_history, get_source)        |
       +------------------------------+------------------------------+
                                      |
       +------------------------------v------------------------------+
       |                   GraphRepository (Ashwin)                  |
       |                 FalkorDB / Harbor Fixtures                  |
       +-------------------------------------------------------------+
```

### Key Principles
1. **Facts originate from the graph**: The model never creates graph state, changes knowledge versions, or executes graph mutations.
2. **Server-owned `effective_at`**: The server's `preview_created_at` timestamp is copied into extracted proposals after validation. The model is never permitted to select or predict the decision's effective time.
3. **No automatic downstream schedule recalculation**: Upstream delays (such as `wi_permissions` slipping to October 28) do NOT magically reschedule downstream feature forecasts (`wi_sso` October 23). The AI explicitly highlights the discrepancy as requiring replanning.
4. **No silent mocks**: Live provider failures (timeouts, schema parsing errors, authentication failures) result in labelled partial results with explicit error warnings. A test double is used strictly for offline development and CI.

---

## 2. Two Bounded Question Types

To prevent hallucinations and unbounded reasoning loops, the agent supports exactly two question types:

### Question Type 1: Affected Promises and Accountable Owners
- **Intent**: Determine which customer commitments are in `date_conflict`, identify blocking components, and route follow-ups to responsible parties.
- **Example Queries**:
  - *"What commitments are impacted by the permissions delivery update?"*
  - *"Tell me about Acme SSO status and who is accountable."*
  - *"How does the delay affect Birch audit logging?"*
- **Grounding Rules**:
  - For `date_conflict`: Engineering owner is the **unique owner across all blocking components** (e.g. `person_priya` for permissions in the canonical scenario), NOT the required feature owner.
  - Account owner is resolved from the customer's `ACCOUNT_OWNER` relationship (e.g. `person_maya` for Acme, `person_nisha` for Birch).
  - Missing or ambiguous ownership returns `None` and an explicit limitation warning; no saveable draft is created.
  - Generates two validated drafts citing the promise, dependency, and revised forecast:
    1. `internal_escalation` assigned to the blocking component engineering owner.
    2. `customer_update` assigned to the account owner.

### Question Type 2: Forecast and Decision Lineage
- **Intent**: Explain why a delivery milestone changed, tracking provenance from establishing Decisions to superseded decisions and source documents.
- **Example Queries**:
  - *"Why did the permissions forecast change from DEC-12?"*
  - *"What decision established the permissions delivery date?"*
  - *"Show me the history of DEC-12."*
- **Grounding Rules**:
  - Follows `Decision -ESTABLISHES-> Forecast` provenance chains.
  - Baseline forecasts resolve to source-backed baseline Decisions (e.g. `DEC-12`).
  - Revised forecasts resolve to new live decisions (e.g. `dec_live_permissions_001`) with explicit `SUPERSEDES` links.
  - Follows establishing decision citations to real source documents (`get_source`) and cites exact quotes.
  - Explains explicit milestone transition (old delivery date -> new delivery date).
  - Does NOT invent unrecorded business rationales (e.g., claiming "budget cuts" or "team attrition" unless explicitly stated in the source text).

---

## 3. Tool Suite, Declarations & Genuine Model Tool Calling

The agent accesses graph truth via `AgentTools` using genuine function declarations:

| Tool | Signature | Purpose & Evidence Captured |
| --- | --- | --- |
| `resolve_entity` | `(query: str, kind: str?) -> list[dict]` | Matches IDs, names, and aliases while preserving ambiguity. |
| `find_impacted_commitments` | `(as_of: int?) -> dict` | Returns all 4 commitment statuses, blockers, and completeness flags. |
| `get_evidence` | `(commitment_id: str, as_of: int?) -> dict` | Bundles dependency paths, confirmed blockers, and source citations. |
| `get_owners` | `(commitment_id: str, as_of: int?) -> dict` | Resolves accountable engineering and account owners per R1 rules. |
| `get_forecast_history` | `(work_item_id: str) -> dict` | Retrieves accepted forecast intervals, establishing decisions, and citations. |
| `get_source` | `(source_id: str) -> dict` | Fetches full title, body, and timestamp of a source document. |
| `draft_followup` | `(kind, commitment_id, assignee_id, body, citations, based_on_decisions) -> Draft` | Formats and registers a structured draft grounded in retrieved facts. |

### Genuine Tool Loop & Budget Limits
- **Model-Driven Tool Selection**: The LLM receives function declarations for all 7 tools and chooses which tool to invoke. The model resolves entities with `resolve_entity` before looking up commitments or histories.
- **Strict Budget**: The agent is allowed at most **6 tool calls** per run. Attempting a 7th call raises `ToolBudgetExceededError`, terminating tool execution and producing a partial result with accumulated evidence.
- **Total Deadline**: The agent enforces a total run timeout of 30 seconds (`TOTAL_AGENT_TIMEOUT_SECONDS`).
- **Structured Trace**: Every tool execution records:
  ```json
  {
    "tool": "get_evidence",
    "arguments": {"commitment_id": "com_acme_sso", "as_of": 1792240151000},
    "evidence_ids": ["src_permissions_ticket", "src_acme_handoff"],
    "status": "ok"
  }
  ```
- **Privacy Guarantee**: Tool trace records tool names, parameters, evidence IDs, and statuses only. Private chain-of-thought and internal scratchpads are never logged or exposed.

---

## 4. Decision Extraction & Validation Gating

`extract_decision(text, candidates, source_id, now, provider)` turns unstructured engineering notes into immutable preview proposals:

```python
DecisionProposal(
    work_item_id="wi_permissions",
    available_at=1793212199999,  # Oct 28, 2026 IST EOD
    effective_at=now,             # Pavan's preview_created_at
    supersedes_id="DEC-12",
    owner_id="person_priya",
    evidence_quote="Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12."
)
```

### Review Triggers & Server Validation
The extractor immediately halts and raises `ReviewRequiredError` (HTTP 422 `review_required`) when encountering:
1. **Custom Decision-Effective Time**: Notes specifying retroactive or future effective times (e.g. *"effective retroactively from Oct 1"*, *"decision effective tomorrow"*, *"effective from 6 PM"*). Live updates strictly use server preview time. Future delivery dates remain supported.
2. **Missing / Ambiguous Year**: Delivery dates lacking an explicit 4-digit year (e.g. *"October 28"* without 2026).
3. **Date Verification**: The extracted date MUST actually appear in the source text. Non-matching or unparseable dates trigger review.
4. **Ownership Reassignment**: Notes attempting to transfer ownership to an unrecorded individual. Ownership changes require separate governance.
5. **Entity Ambiguity & Resolution**: If a query matches multiple entities (e.g. multiple people with the same name), review is requested (`ambiguous_entity`).
6. **Conflicting / Inverted Dates**: Stating delivery moves backward without justification (e.g. from Oct 28 to Oct 21) triggers `conflicting_dates`.
7. **Verbatim Quote Check**: `evidence_quote` must be an exact verbatim substring of the source note text (`ExtractionValidationError`). Line substitution is strictly forbidden.
8. **Provider Requirement**: An explicit `LLMProvider` is required. The extractor will not silently fall back to an unverified mock when live AI is missing.

---

## 5. Grounding Verification & Draft Safety

The grounding layer (`backend/app/ai/grounding.py`) validates all model outputs before they are returned:

### 1. Exact Verbatim Quote Verification
Every `SourceRef.quote` must be an exact substring of the stored `Source.body`. If the model paraphrases or hallucinates a quote, the citation is dropped and a warning is logged.

### 2. Follow-Up Draft Guardrails
- **Internal Escalation**:
  - Must be assigned to the blocking component owner.
  - If engineering ownership is missing or ambiguous across blockers, draft generation is aborted with a warning.
- **Customer Update**:
  - Must be assigned to the account owner.
  - If account owner is missing, draft generation is aborted.
  - **Forbidden Phrasing Rejection**:
    - *Breach claims*: Words like *"in breach of contract"*, *"we have breached"* are rejected (commitments are future-dated).
    - *Synthetic loss*: Financial claims like *"$100,000 lost"*, *"damages owed"* are rejected.
    - *Invented delivery dates*: Stating un-sourced replacement dates like *"rescheduled delivery will be Nov 18"* is rejected.
- **Mandatory Sourcing**: A draft with zero valid verified citations is rejected.

---

## 6. Seed Mappings vs. Live Extraction & Verification Record

| Dimension | Seed / Baseline Knowledge | Live Decision Note |
| --- | --- | --- |
| **Ingestion Path** | Deterministic fixture loader (`fixtures/harbor/`) | Real extraction engine (`extract_decision`) |
| **Provenance** | Pre-seeded baseline decisions (`DEC-12`, `dec_baseline_*`) | Dynamically extracted proposal with `supersedes_id` |
| **Validation** | Verified by fixture integrity tests (`tests/graph/test_fixtures.py`) | Runtime validation against graph candidates and exact quotes |
| **Effective Time** | Historical seeded timestamps (October 1, 2026) | Server `preview_created_at` at preview generation |
| **Test Verification Record** | Checked deterministically in `tests/ai/test_harbor_fixtures.py` | Unit and integration test suite exercises deterministic test doubles to verify schema, review triggers, and quote bounds; live Gemini smoke tests are executed when `LLM_API_KEY` is provided. |

---

## 7. Failure Modes & Fallback Behavior

| Failure Mode | Behavior | User/API Impact |
| --- | --- | --- |
| **Provider Timeout** | Caught by agent; logs warning and invokes deterministic grounded answer template. | Returns HTTP 200 with `status: "partial"`, grounded facts, verified citations, and explicit warning. |
| **Schema Validation Error** | Model output fails Pydantic schema validation. | Re-raises `ProviderSchemaError` or returns grounded partial response. |
| **Stale Version** | `request.expected_version != repo.get_version()` | Raises `StaleEvidenceError`, mapped by FastAPI to HTTP 409 `stale_evidence`. |
| **Missing Evidence / Owner** | Incomplete dependency chain or missing owner in graph. | Generates `status: "partial"`, lists warnings in response, suppresses invalid drafts. |
| **Tool Budget Limit** | 7th tool call attempted. | Halts further queries; returns partial status with accumulated evidence. |
| **Overall Deadline Hit** | Total run exceeds 30s. | Returns `status: "partial"` with deadline warning and accumulated facts. |
