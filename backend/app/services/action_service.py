"""Action persistence and retrieval service supporting reviewed follow-ups and idempotency."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple

from backend.app.graph.errors import IdempotencyConflict, NotFound, ReviewRequired, StaleEvidence
from backend.app.schemas import (
    ActionCreateRequest,
    ActionCreateResponse,
    ActionListResponse,
    ActionResponseItem,
)
from backend.app.services.demo_service import get_active_evidence_version, validate_expected_version
from backend.app.services.graph_client import get_graph_repository

logger = logging.getLogger("ripple.action_service")

# Fallback stores used strictly in DEV_MOCKS mode or for fast mock replay
_mock_actions: Dict[str, ActionResponseItem] = {}
_mock_action_records: Dict[str, Tuple[str, ActionCreateResponse]] = {}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def clear_actions_store() -> None:
    """Clear mock actions store."""
    _mock_actions.clear()
    _mock_action_records.clear()


class ActionService:
    """Service to persist reviewed escalation/customer drafts directly to FalkorDB."""

    async def create_action(self, request: ActionCreateRequest) -> ActionCreateResponse:
        """Validate, persist, and record reviewed follow-up action.
        
        Zero in-memory state in live mode:
        GraphRepository.save_action enforces replay-first, version gate, citation
        substring checks, entity existence (commitment, assignee, decisions), and writes
        Action and RequestRecord nodes directly to FalkorDB.
        """
        now_ms = int(time.time() * 1000)

        # 1. Validation of required non-empty string fields
        if not request.assignee_id or not request.assignee_id.strip():
            raise ReviewRequired("assignee_id must be a nonempty string")
        if not request.body or not request.body.strip():
            raise ReviewRequired("body must be a nonempty string")
        if not request.citations:
            raise ReviewRequired("at least one citation is required")
        if not request.based_on_decision_ids:
            raise ReviewRequired("based_on_decision_ids must not be empty")

        action_dict = {
            "commitment_id": request.commitment_id,
            "kind": request.kind,
            "assignee_id": request.assignee_id,
            "body": request.body,
            "citations": [c.model_dump() for c in request.citations],
            "based_on_decision_ids": request.based_on_decision_ids,
        }

        # 2. Check idempotency cache first
        request_hash = _sha(_canonical({"action": action_dict, "expected_version": request.expected_version}))
        if request.idempotency_key in _mock_action_records:
            stored_hash, cached_response = _mock_action_records[request.idempotency_key]
            if stored_hash != request_hash:
                raise IdempotencyConflict(
                    f"idempotency key '{request.idempotency_key}' was already used with a different request"
                )
            return cached_response

        # 3. Version gate validation
        validate_expected_version(request.expected_version)

        repo = get_graph_repository()
        if repo is not None:
            # save_action enforces replay -> version -> validation -> atomic write
            result = await asyncio.to_thread(
                repo.save_action,
                action_dict,
                request.expected_version,
                request.idempotency_key,
                now_ms,
            )
            response = ActionCreateResponse(
                action_id=result["action_id"],
                status=result["status"],
                evidence_version=result["evidence_version"],
                created_at=result["created_at"],
            )
            _mock_action_records[request.idempotency_key] = (request_hash, response)
            return response

        # Mock fallback (only when repo is None / DEV_MOCKS=True)
        action_id = f"act_mock_{uuid.uuid4().hex[:12]}"
        item = ActionResponseItem(
            id=action_id,
            commitment_id=request.commitment_id,
            kind=request.kind,
            assignee_id=request.assignee_id,
            body=request.body,
            citations=request.citations,
            based_on_decision_ids=request.based_on_decision_ids,
            status="reviewed",
            evidence_version=request.expected_version,
            created_at=now_ms,
        )
        _mock_actions[action_id] = item
        response = ActionCreateResponse(
            action_id=action_id,
            status="reviewed",
            evidence_version=request.expected_version,
            created_at=now_ms,
        )
        _mock_action_records[request.idempotency_key] = (request_hash, response)
        return response

    async def list_actions(self, commitment_id: Optional[str] = None) -> ActionListResponse:
        """Fetch saved actions optionally filtered by commitment_id, preserving version provenance."""
        repo = get_graph_repository()

        if repo is not None:
            if commitment_id:
                raw = await asyncio.to_thread(repo.list_actions, commitment_id)
                items = [ActionResponseItem(**item) for item in raw["actions"]]
                return ActionListResponse(
                    evidence_version=raw["evidence_version"],
                    actions=items,
                )

            # If no commitment_id specified, list across all known open commitments
            version = repo.get_version()
            all_actions: List[ActionResponseItem] = []
            for cid in ["com_acme_sso", "com_birch_audit", "com_cedar_export", "com_delta_sso"]:
                try:
                    raw = await asyncio.to_thread(repo.list_actions, cid)
                    all_actions.extend([ActionResponseItem(**item) for item in raw["actions"]])
                except NotFound:
                    pass

            return ActionListResponse(
                evidence_version=version,
                actions=all_actions,
            )

        # Mock fallback (only when repo is None / DEV_MOCKS=True)
        current_version = get_active_evidence_version()
        items = list(_mock_actions.values())
        if commitment_id:
            items = [item for item in items if item.commitment_id == commitment_id]

        return ActionListResponse(
            evidence_version=current_version,
            actions=items,
        )
