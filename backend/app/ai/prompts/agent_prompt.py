"""Agent prompts and reasoning schemas for Ripple bounded AI agent."""

from __future__ import annotations

import json
from typing import Literal
from pydantic import BaseModel, Field


class RawCitation(BaseModel):
    source_id: str
    quote: str


class RawDraft(BaseModel):
    kind: Literal["internal_escalation", "customer_update"]
    commitment_id: str
    assignee_id: str | None = None
    body: str
    citations: list[RawCitation] = Field(default_factory=list)
    based_on_decision_ids: list[str] = Field(default_factory=list)


class RawAgentOutput(BaseModel):
    """Raw structured output from model before grounding validation."""

    answer: str
    citations: list[RawCitation] = Field(default_factory=list)
    drafts: list[RawDraft] = Field(default_factory=list)


AGENT_SYSTEM_PROMPT = """You are an authoritative, grounded AI assistant for Ripple, an engineering commitments and dependency governance platform.

You answer two bounded types of questions:
1. Impact and accountable owners (commitments impacted by forecast delays, accountable engineering/account owners).
2. Forecast and decision lineage (why a forecast changed, establishing Decision, superseded predecessor, and source citations).

CRITICAL GROUNDING RULES:
1. CITATIONS:
   - Every citation quote must be an EXACT verbatim substring of the tool-retrieved source body.
   - Do not paraphrase quoted evidence.

2. FORECAST PROVENANCE & DOWNSTREAM SCHEDULES:
   - Downstream feature forecasts are NOT automatically recalculated when an upstream dependency slips.
   - You MUST distinguish between a recorded feature forecast and a conflicting dependency forecast, explaining that the discrepancy requires replanning.
   - For lineage questions, cite the establishing Decision and superseded predecessor. Do not guess unrecorded business reasons.

3. DRAFTING CONSTRAINTS:
   - Internal escalation drafts must be assigned to the blocking component engineering owner.
   - Customer update drafts must be assigned to the account owner.
   - Customer drafts must NEVER claim a breach has occurred, NEVER invent a future replacement delivery date, and NEVER describe synthetic contract values as actual monetary loss.
   - If an engineering or account owner is missing, do not produce a draft for that role.
"""


def build_agent_prompt(
    user_message: str,
    commitment_id: str | None,
    tool_evidence: dict,
) -> str:
    """Format user message and retrieved tool facts for LLM generation."""
    evidence_str = json.dumps(tool_evidence, indent=2, default=str)
    return f"""User Message:
{user_message}

Selected Commitment Context: {commitment_id or "None"}

Retrieved Tool Evidence from Graph:
---
{evidence_str}
---

Generate an answer grounded strictly in the tool evidence above, along with relevant follow-up drafts (internal escalation to engineering owner, customer update to account owner) if a date conflict exists."""

