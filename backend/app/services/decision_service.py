"""Decision preview extraction and atomic confirmation service."""

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.ai.extraction import extract_decision
from backend.app.ai.prompts.extraction_prompt import RawExtractedProposal
from backend.app.ai.provider import (
    DeterministicTestDouble,
    LLMProvider,
    get_provider,
)
from backend.app.graph.errors import (
    IdempotencyConflict,
    ReviewRequired,
    StaleEvidence,
)
from backend.app.graph.seed import load_fixtures
from backend.app.schemas import (
    DecisionConfirmRequest,
    DecisionConfirmResponse,
    DecisionPreviewRequest,
    DecisionPreviewResponse,
    DecisionProposal,
)
from backend.app.services.demo_service import (
    get_active_evidence_version,
    validate_expected_version,
)
from backend.app.services.graph_client import get_graph_repository
from backend.app.services.preview_store import PreviewRecord, get_preview_store
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.decision_service")

# Cached candidate entities for candidate resolution in extraction
_cached_candidates: Optional[Dict[str, Any]] = None

# Mock confirm idempotency records
_mock_confirm_records: Dict[str, Tuple[str, DecisionConfirmResponse]] = {}


def _sha(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def clear_decision_store() -> None:
    """Clear mock decision confirmation idempotency records."""
    _mock_confirm_records.clear()


def _get_candidates() -> Dict[str, Any]:
    """Load candidate graph entities for extract_decision validation."""
    global _cached_candidates
    if _cached_candidates is not None:
        return _cached_candidates

    fixtures_dir = Path(__file__).resolve().parents[3] / "fixtures" / "harbor"
    if fixtures_dir.exists():
        data = load_fixtures(str(fixtures_dir))
        owners = {
            r["to_id"]: r["from_id"]
            for r in data["relationships"]
            if r.get("type") == "OWNS"
        }
        _cached_candidates = {
            "work_items": data["work_items"],
            "people": data["people"],
            "work_item_owners": owners,
            "decisions": data["decisions"],
            "aliases": data.get("aliases", []),
        }
    else:
        _cached_candidates = {
            "work_items": [],
            "people": [],
            "work_item_owners": {},
            "decisions": [],
            "aliases": [],
        }
    return _cached_candidates


def _make_fallback_test_double(text: str) -> DeterministicTestDouble:
    """Create a deterministic extraction test double when no live LLM API key is configured."""
    # Delivery date: ISO YYYY-MM-DD
    delivery_date = "2026-10-28"
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        delivery_date = iso_match.group(1)

    # Identify work item
    wi_str = "permissions"
    for candidate_wi in ["permissions", "identity migration", "sso", "audit", "export"]:
        if candidate_wi in text.lower():
            wi_str = candidate_wi
            break

    # Identify owner
    owner_str = "Priya"
    for candidate_owner in ["Priya", "Lena", "Omar", "Eli", "Maya", "Nisha", "Leo", "Noah"]:
        if candidate_owner.lower() in text.lower():
            owner_str = candidate_owner
            break

    # Identify superseded decision
    supersedes = "DEC-12"
    dec_match = re.search(r"\b(DEC-\d+)\b", text, re.IGNORECASE)
    if dec_match:
        supersedes = dec_match.group(1).upper()

    # Quote must be a true substring of text
    quote = text
    if "delivery moves" in text:
        quote = text[text.find("delivery moves"):]
        if "." in quote:
            quote = quote[:quote.find(".")].strip()
    elif "moves to" in text:
        quote = text[text.find("moves to"):]
        if "." in quote:
            quote = quote[:quote.find(".")].strip()

    return DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id=wi_str,
                delivery_date=delivery_date,
                supersedes_decision_id=supersedes,
                owner_name_or_id=owner_str,
                evidence_quote=quote,
            )
        }
    )


class DecisionService:
    """Service orchestrating decision extraction preview and atomic confirmation under R1."""

    async def preview_decision(self, request: DecisionPreviewRequest) -> DecisionPreviewResponse:
        """Extract proposal from text, assign server effective_at, validate and store transient preview."""
        now_ms = int(time.time() * 1000)
        current_version = get_active_evidence_version()
        text = request.text.strip()
        settings = get_settings()

        # R1 Rule 4: Reject requests for custom historical/future decision effective times with 422 review_required
        backdated_patterns = [
            r"\bbackdate\b",
            r"\beffective as of\b",
            r"\bretroactiv\w*",
            r"\beffective from\b",
        ]
        if any(re.search(pat, text, re.IGNORECASE) for pat in backdated_patterns):
            raise ReviewRequired("Requests for custom or backdated decision effective times require human review.")

        # R1 Rule: Reassignment of component ownership requires human review (422 review_required)
        reassign_patterns = [
            r"\breassign owner\b",
            r"\btransfer ownership\b",
            r"\bchange owner\b",
        ]
        if any(re.search(pat, text, re.IGNORECASE) for pat in reassign_patterns):
            raise ReviewRequired("Reassignment of component ownership requires human review.")

        # Ambiguous / unparseable text check
        if not any(k in text.lower() for k in ["permissions", "identity", "sso", "audit", "export", "work_item", "delivery", "moves"]):
            raise ReviewRequired("Unparseable or ambiguous decision note requires human review.")

        candidates = _get_candidates()
        source_id = f"src_{uuid.uuid4().hex[:12]}"

        # Select LLM provider
        if settings.llm_api_key:
            provider: LLMProvider = get_provider(
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                base_url=settings.llm_base_url,
            )
        else:
            provider = _make_fallback_test_double(text)

        # Call authoritative decision extraction module
        proposal = await extract_decision(
            text=text,
            candidates=candidates,
            source_id=source_id,
            now=now_ms,
            provider=provider,
        )

        # Generate unique preview_id and store in PreviewStore (15-min TTL)
        preview_id = f"prev_{uuid.uuid4().hex[:12]}"
        preview_store = get_preview_store()
        record = preview_store.put(
            preview_id=preview_id,
            proposal=proposal,
            evidence_version=current_version,
            text=text,
            source_title=request.source_title,
            source_id=source_id,
            now_ms=now_ms,
        )

        return DecisionPreviewResponse(
            preview_id=record.preview_id,
            evidence_version=record.evidence_version,
            expires_at=record.expires_at,
            proposal=record.proposal,
            warnings=[],
        )

    async def confirm_decision(self, request: DecisionConfirmRequest) -> DecisionConfirmResponse:
        """Atomically confirm an unexpired proposal preview, establishing a new forecast in FalkorDB."""
        now_ms = int(time.time() * 1000)

        # 1. Check idempotency cache first
        confirm_hash = _sha(request.preview_id, request.expected_version)
        if request.idempotency_key in _mock_confirm_records:
            stored_hash, cached_response = _mock_confirm_records[request.idempotency_key]
            if stored_hash != confirm_hash:
                raise IdempotencyConflict(
                    f"idempotency key '{request.idempotency_key}' was already used with a different request"
                )
            return cached_response

        # 2. Lookup preview record (raises PreviewExpiredError if unknown or already confirmed)
        preview_store = get_preview_store()
        record: PreviewRecord = preview_store.get(request.preview_id)

        proposal_dict = {
            "work_item_id": record.proposal.work_item_id,
            "available_at": record.proposal.available_at,
            "effective_at": record.proposal.effective_at,
            "owner_id": record.proposal.owner_id,
            "evidence_quote": record.proposal.evidence_quote,
            "supersedes_id": record.proposal.supersedes_id,
        }

        source_dict = {
            "id": record.source_id,
            "type": "decision_record",
            "title": record.source_title,
            "body": record.text,
            "source_timestamp": record.created_at,
        }

        repo = get_graph_repository()

        # Step 3: If proposal has expired, check for replay before rejecting with 410
        if record.is_expired(now_ms):
            if repo is not None:
                replayed = await asyncio.to_thread(
                    repo.replay_confirm,
                    proposal_dict,
                    source_dict,
                    request.expected_version,
                    request.idempotency_key,
                )
                if replayed is not None:
                    response = DecisionConfirmResponse(
                        decision_id=replayed["decision_id"],
                        evidence_version=replayed["evidence_version"],
                        changed_work_item_ids=replayed["changed_work_item_ids"],
                    )
                    _mock_confirm_records[request.idempotency_key] = (confirm_hash, response)
                    return response
            preview_store.pop(request.preview_id)
            from backend.app.errors import PreviewExpiredError
            raise PreviewExpiredError(
                f"Preview proposal '{request.preview_id}' has expired.",
                details={"preview_id": request.preview_id},
            )

        # Step 4: Validate expected version
        validate_expected_version(request.expected_version)

        # Step 5: Proposal is live; execute atomic confirm in GraphRepository
        if repo is not None:
            result = await asyncio.to_thread(
                repo.confirm_decision,
                proposal_dict,
                source_dict,
                request.expected_version,
                request.idempotency_key,
                now_ms,
            )
            preview_store.pop(request.preview_id)
            response = DecisionConfirmResponse(
                decision_id=result["decision_id"],
                evidence_version=result["evidence_version"],
                changed_work_item_ids=result["changed_work_item_ids"],
            )
            _mock_confirm_records[request.idempotency_key] = (confirm_hash, response)
            return response

        # Mock fallback (only when repo is None / DEV_MOCKS=True)
        preview_store.pop(request.preview_id)
        from backend.app.services.demo_service import bump_knowledge_revision
        new_version = bump_knowledge_revision()
        response = DecisionConfirmResponse(
            decision_id="DEC-13",
            evidence_version=new_version,
            changed_work_item_ids=[record.proposal.work_item_id],
        )
        _mock_confirm_records[request.idempotency_key] = (confirm_hash, response)
        return response
