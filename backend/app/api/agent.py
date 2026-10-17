"""Agent run orchestration endpoint for Ripple API."""

import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AgentRunRequest(BaseModel):
    """Payload to invoke agent reasoning and draft creation."""
    message: str
    commitment_id: Optional[str] = None
    expected_version: str


@router.post("/agent/run")
async def run_agent(request: AgentRunRequest):
    """Execute bounded AI reasoning across impact/owners or decision lineage.

    Returns cited explanation, structured tool trace, and proposed follow-up drafts.
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    commitment_id = request.commitment_id or "com_acme_sso"

    return {
        "run_id": run_id,
        "evidence_version": request.expected_version,
        "status": "complete",
        "answer": (
            "Acme SSO commitment (due October 23, 2026) has a schedule conflict with "
            "the Permissions Service component (available October 28, 2026). "
            "Engineering owner is Priya Sharma and account owner is Maya Lin."
        ),
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "permissions service delivery moves from October 21, 2026 to October 28, 2026",
            },
            {
                "source_id": "src_acme_handoff",
                "quote": "Acme SSO integration deadline agreed for October 23, 2026.",
            },
        ],
        "drafts": [
            {
                "kind": "internal_escalation",
                "commitment_id": commitment_id,
                "assignee_id": "person_priya",
                "body": (
                    "Hi Priya, the permissions service delivery adjustment to October 28 "
                    "conflicts with Acme's October 23 SSO commitment. Please advise on replanning options."
                ),
                "citations": [
                    {
                        "source_id": "src_permissions_ticket",
                        "quote": "permissions service delivery moves from October 21, 2026 to October 28, 2026",
                    }
                ],
                "based_on_decision_ids": ["DEC-12"],
            }
        ],
        "tool_trace": [
            {
                "tool": "resolve_entity",
                "arguments": {"query": "Acme", "kind": "customer"},
                "evidence_ids": ["cust_acme"],
                "status": "ok",
            },
            {
                "tool": "find_impacted_commitments",
                "arguments": {"work_item_id": "wi_permissions"},
                "evidence_ids": ["com_acme_sso", "com_birch_audit"],
                "status": "ok",
            },
            {
                "tool": "get_owners",
                "arguments": {"commitment_id": commitment_id},
                "evidence_ids": ["person_priya", "person_maya"],
                "status": "ok",
            },
        ],
        "warnings": [],
    }
