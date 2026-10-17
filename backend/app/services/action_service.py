"""Action persistence and retrieval service supporting reviewed follow-ups and idempotency."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Dict, List, Optional

from backend.app.errors import IdempotencyConflictError, ReviewRequiredError
from backend.app.schemas import (
    ActionCreateRequest,
    ActionCreateResponse,
    ActionListResponse,
    ActionResponseItem,
)
from backend.app.services.demo_service import (
    get_active_dataset_id,
    get_active_evidence_version,
    validate_expected_version,
)
from backend.app.services.graph_client import get_graph_repository
from backend.app.services.source_service import SourceService
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.action_service")

# In-memory store for actions when running in mock mode or dev fallback
# id -> ActionResponseItem
_in_memory_actions: Dict[str, ActionResponseItem] = {}

# Idempotency store for actions: (dataset_id, "save_action", idempotency_key) -> (req_hash, result_dict)
_action_idempotency_records: Dict[tuple, tuple] = {}


def clear_actions_store() -> None:
    """Clear in-memory actions (e.g. during demo reset)."""
    _in_memory_actions.clear()
    _action_idempotency_records.clear()


class ActionService:
    """Service to persist reviewed escalation/customer drafts with idempotency protection."""

    def __init__(self):
        self.source_service = SourceService()

    async def create_action(self, request: ActionCreateRequest) -> ActionCreateResponse:
        """Validate, persist, and record reviewed follow-up action under idempotency lock."""
        now_ms = int(time.time() * 1000)
        current_dataset = get_active_dataset_id()
        current_version = get_active_evidence_version()

        # 1. Validate non-empty required fields
        if not request.assignee_id.strip():
            raise ReviewRequiredError("Action must have an assigned owner (assignee_id).")
        if not request.body.strip():
            raise ReviewRequiredError("Action draft body cannot be empty.")
        if not request.citations:
            raise ReviewRequiredError("Action must cite at least one supporting evidence source.")
        if not request.based_on_decision_ids:
            raise ReviewRequiredError("Action must reference establishing decision IDs.")

        # 2. Validate citations quotes exist against source text
        for citation in request.citations:
            try:
                src = await self.source_service.get_source(citation.source_id)
                if citation.quote not in src.body:
                    logger.warning(
                        "Citation quote '%s' not found verbatim in source '%s'; recording warning.",
                        citation.quote,
                        citation.source_id,
                    )
            except Exception as exc:
                logger.warning("Could not verify citation source %s: %s", citation.source_id, exc)

        # 3. Version validation against active evidence revision
        validate_expected_version(request.expected_version)

        # 4. Idempotency Check: (dataset_id, "save_action", idempotency_key)
        req_hash = hashlib.sha256(
            f"{request.expected_version}:{request.commitment_id}:{request.kind}:{request.assignee_id}:{request.body}".encode("utf-8")
        ).hexdigest()
        idem_key = (current_dataset, "save_action", request.idempotency_key)

        if idem_key in _action_idempotency_records:
            cached_hash, cached_resp = _action_idempotency_records[idem_key]
            if cached_hash != req_hash:
                raise IdempotencyConflictError(
                    f"Idempotency key '{request.idempotency_key}' was previously used with different parameters.",
                    details={"idempotency_key": request.idempotency_key},
                )
            logger.info("Replaying cached action creation response for key %s", request.idempotency_key)
            return ActionCreateResponse(**cached_resp)

        # 5. Persist to GraphRepository if available
        action_id = f"act_{uuid.uuid4().hex[:12]}"
        repo = get_graph_repository()

        if repo is not None and hasattr(repo, "save_action"):
            try:
                repo_result = await asyncio.to_thread(
                    repo.save_action,
                    action_id=action_id,
                    action_data=request.model_dump(),
                    created_at=now_ms,
                    evidence_version=current_version,
                )
                if isinstance(repo_result, dict) and "action_id" in repo_result:
                    action_id = repo_result["action_id"]
            except Exception as exc:
                logger.error("Error saving action in GraphRepository: %s", exc)
                settings = get_settings()
                if not settings.dev_mocks:
                    raise

        # 6. Store in in-memory repository
        stored_item = ActionResponseItem(
            id=action_id,
            commitment_id=request.commitment_id,
            kind=request.kind,
            assignee_id=request.assignee_id,
            body=request.body,
            citations=request.citations,
            based_on_decision_ids=request.based_on_decision_ids,
            status="reviewed",
            evidence_version=current_version,
            created_at=now_ms,
        )
        _in_memory_actions[action_id] = stored_item

        response = ActionCreateResponse(
            action_id=action_id,
            status="reviewed",
            evidence_version=current_version,
            created_at=now_ms,
        )

        # 7. Record idempotency entry
        _action_idempotency_records[idem_key] = (req_hash, response.model_dump())
        logger.info("Action created successfully: action_id=%s, version=%s", action_id, current_version)
        return response

    async def list_actions(self, commitment_id: Optional[str] = None) -> ActionListResponse:
        """Fetch saved actions optionally filtered by commitment_id, preserving version provenance."""
        current_version = get_active_evidence_version()
        repo = get_graph_repository()

        if repo is not None and hasattr(repo, "list_actions"):
            try:
                raw_actions = await asyncio.to_thread(repo.list_actions, commitment_id)
                if isinstance(raw_actions, list):
                    items = [ActionResponseItem(**item) for item in raw_actions]
                    return ActionListResponse(
                        evidence_version=current_version,
                        actions=items,
                    )
            except Exception as exc:
                logger.error("Error listing actions from GraphRepository: %s", exc)
                settings = get_settings()
                if not settings.dev_mocks:
                    raise

        # Fallback to in-memory store
        items = list(_in_memory_actions.values())
        if commitment_id:
            items = [item for item in items if item.commitment_id == commitment_id]

        # Seed with initial canonical action if empty to support Jay's UI exploration
        if not items and not _in_memory_actions:
            canonical_action = ActionResponseItem(
                id="act_canonical_001",
                commitment_id="com_acme_sso",
                kind="internal_escalation",
                assignee_id="person_priya",
                body="Priya: Acme SSO is promised for October 23, 2026. Please align on replanning options.",
                citations=[],
                based_on_decision_ids=["DEC-13"],
                status="reviewed",
                evidence_version=current_version,
                created_at=int(time.time() * 1000) - 60000,
            )
            items = [canonical_action]

        return ActionListResponse(
            evidence_version=current_version,
            actions=items,
        )
