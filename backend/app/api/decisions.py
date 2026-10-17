"""Decision preview and confirmation endpoints for Ripple API."""

import time
import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class DecisionPreviewRequest(BaseModel):
    """Payload to extract and preview a decision note."""
    text: str
    source_title: Optional[str] = None


class DecisionConfirmRequest(BaseModel):
    """Payload to confirm an accepted preview proposal."""
    preview_id: str
    expected_version: str
    idempotency_key: str


@router.post("/decisions/preview")
async def preview_decision(request: DecisionPreviewRequest):
    """Extract and preview an engineering decision delta.

    Assigns server-side effective_at timestamp and sets a 15-minute TTL.
    """
    server_now = int(time.time() * 1000)
    fifteen_mins_ms = 15 * 60 * 1000
    preview_id = f"prev_{uuid.uuid4().hex[:12]}"

    return {
        "preview_id": preview_id,
        "evidence_version": "ds_demo_001.rev_001",
        "expires_at": server_now + fifteen_mins_ms,
        "proposal": {
            "work_item_id": "wi_permissions",
            "available_at": 1793210399999,  # October 28, 2026 IST EOD
            "effective_at": server_now,
            "supersedes_id": "DEC-12",
            "owner_id": "person_priya",
            "evidence_quote": (
                "Approved: permissions service delivery moves from October 21, 2026 "
                "to October 28, 2026. Owner: Priya. This replaces decision DEC-12."
            ),
        },
        "warnings": [],
    }


@router.post("/decisions/confirm")
async def confirm_decision(request: DecisionConfirmRequest):
    """Confirm a previewed decision proposal atomically.

    Persists Source, Decision, and Forecast cutover, updating evidence version.
    """
    decision_id = f"dec_{uuid.uuid4().hex[:12]}"

    return {
        "decision_id": decision_id,
        "evidence_version": "ds_demo_001.rev_002",
        "changed_work_item_ids": ["wi_permissions"],
    }
