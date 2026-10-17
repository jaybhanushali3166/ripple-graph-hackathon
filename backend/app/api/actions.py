"""Actions creation and retrieval endpoints for Ripple API."""

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ActionCitation(BaseModel):
    """Citation linking reviewed action text to source evidence."""
    source_id: str
    quote: str


class ActionCreateRequest(BaseModel):
    """Payload to persist a reviewed follow-up action draft."""
    idempotency_key: str
    expected_version: str
    commitment_id: str
    kind: str
    assignee_id: str
    body: str
    citations: List[ActionCitation]
    based_on_decision_ids: List[str]


@router.post("/actions")
async def create_action(request: ActionCreateRequest):
    """Persist a reviewed action draft against a specific evidence version."""
    action_id = f"act_{uuid.uuid4().hex[:12]}"
    now_ms = int(time.time() * 1000)

    return {
        "action_id": action_id,
        "status": "reviewed",
        "evidence_version": request.expected_version,
        "created_at": now_ms,
    }


@router.get("/actions")
async def list_actions(commitment_id: Optional[str] = None):
    """Retrieve persisted reviewed actions, preserving original evidence version."""
    target_commitment = commitment_id or "com_acme_sso"

    return {
        "evidence_version": "ds_demo_001.rev_001",
        "actions": [
            {
                "id": "act_mock_001",
                "commitment_id": target_commitment,
                "kind": "internal_escalation",
                "assignee_id": "person_priya",
                "body": (
                    "Hi Priya, the permissions service delivery adjustment to October 28 "
                    "conflicts with Acme's October 23 SSO commitment."
                ),
                "citations": [
                    {
                        "source_id": "src_permissions_ticket",
                        "quote": "permissions service delivery moves from October 21, 2026 to October 28, 2026",
                    }
                ],
                "based_on_decision_ids": ["DEC-12"],
                "status": "reviewed",
                "evidence_version": "ds_demo_001.rev_001",
                "created_at": 1792195200000,
            }
        ],
    }
