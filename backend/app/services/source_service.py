"""Source and forecast history service for retrieving provenance and timeline from FalkorDB."""

import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

from backend.app.errors import EntityNotFoundError, GraphUnavailableError
from backend.app.schemas import (
    ForecastHistoryItem,
    SourceRef,
    SourceResponse,
    WorkItemHistoryResponse,
)
from backend.app.services.demo_service import get_active_evidence_version
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.source_service")

# Authoritative synthetic fixture sources supporting full demo story
KNOWN_SOURCES: Dict[str, Dict[str, Any]] = {
    "src_permissions_ticket": {
        "id": "src_permissions_ticket",
        "type": "ticket",
        "title": "Permissions Service v2 Delivery Brief",
        "body": "Permissions service delivery is accepted for October 21, 2026. Lead engineer: Priya Sharma. Ref: DEC-12.",
        "source_timestamp": 1792512000000,
    },
    "src_dec12": {
        "id": "src_dec12",
        "type": "decision_record",
        "title": "Decision DEC-12: Permissions Service Delivery",
        "body": "Decision DEC-12: Permissions service delivery scheduled for October 21, 2026. Owner: Priya.",
        "source_timestamp": 1792512000000,
    },
    "src_acme_handoff": {
        "id": "src_acme_handoff",
        "type": "deal_memo",
        "title": "Acme Corp Enterprise Contract and SLA Commitments",
        "body": "Acme SSO integration deadline agreed for October 23, 2026. Account owner: Maya Lin.",
        "source_timestamp": 1792425600000,
    },
    "src_birch_handoff": {
        "id": "src_birch_handoff",
        "type": "deal_memo",
        "title": "Birch Audit Logging Handoff",
        "body": "Birch audit log export capability required by October 26, 2026. Account owner: Nisha Gupta.",
        "source_timestamp": 1792425600000,
    },
    "src_cedar_handoff": {
        "id": "src_cedar_handoff",
        "type": "deal_memo",
        "title": "Cedar Systems Export Agreement",
        "body": "Cedar data export pipeline promised for delivery by October 23, 2026. Account owner: Leo Rossi.",
        "source_timestamp": 1792425600000,
    },
    "src_delta_handoff": {
        "id": "src_delta_handoff",
        "type": "deal_memo",
        "title": "Delta Logistics SSO Handoff",
        "body": "Delta Logistics SSO deployment scheduled by November 5, 2026. Account owner: Noah Kim.",
        "source_timestamp": 1792425600000,
    },
    "src_sso_plan": {
        "id": "src_sso_plan",
        "type": "architecture_doc",
        "title": "SSO Architecture Plan",
        "body": "Single Sign-On implementation plan and dependency specification. Lead: Lena Chen.",
        "source_timestamp": 1792425600000,
    },
    "src_identity_plan": {
        "id": "src_identity_plan",
        "type": "architecture_doc",
        "title": "Identity Migration Plan",
        "body": "Identity migration component architecture and permissions dependency.",
        "source_timestamp": 1792425600000,
    },
    "src_audit_plan": {
        "id": "src_audit_plan",
        "type": "architecture_doc",
        "title": "Audit Service Plan",
        "body": "Audit log export service architecture and dependency mapping. Lead: Omar Patel.",
        "source_timestamp": 1792425600000,
    },
    "src_export_plan": {
        "id": "src_export_plan",
        "type": "architecture_doc",
        "title": "Export Service Plan",
        "body": "Data export worker service architecture and queue mapping. Lead: Eli Vance.",
        "source_timestamp": 1792425600000,
    },
    "src_owners": {
        "id": "src_owners",
        "type": "roster",
        "title": "Engineering and Account Ownership Roster",
        "body": "Ownership assignments: Priya (permissions), Lena (sso, identity migration), Omar (audit), Eli (export), Maya (Acme), Nisha (Birch), Leo (Cedar), Noah (Delta).",
        "source_timestamp": 1792425600000,
    },
}


def _load_canonical_data() -> dict:
    payloads_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "docs",
        "examples",
        "canonical_payloads.json",
    )
    if os.path.exists(payloads_path):
        try:
            with open(payloads_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Could not load canonical_payloads.json: %s", exc)
    return {}


class SourceService:
    """Service to retrieve raw evidence sources and WorkItem forecast cutover histories."""

    async def get_source(self, source_id: str) -> SourceResponse:
        """Fetch raw source text, title, timestamp, and content hash."""
        repo = get_graph_repository()

        if repo is not None:
            try:
                raw_source = await asyncio.to_thread(repo.get_source, source_id)
                if raw_source is None:
                    raise EntityNotFoundError(f"Source '{source_id}' does not exist.")
                if isinstance(raw_source, dict):
                    return SourceResponse(**raw_source)
                return raw_source
            except EntityNotFoundError:
                raise
            except Exception as exc:
                logger.error("Error retrieving source %s from repository: %s", source_id, exc)
                settings = get_settings()
                if not settings.dev_mocks:
                    raise GraphUnavailableError(f"Error querying source '{source_id}': {exc}") from exc

        # Check canonical fixtures dictionary
        if source_id in KNOWN_SOURCES:
            src = KNOWN_SOURCES[source_id]
            body_hash = hashlib.sha256(src["body"].encode("utf-8")).hexdigest()
            return SourceResponse(
                id=src["id"],
                type=src["type"],
                title=src["title"],
                body=src["body"],
                source_timestamp=src["source_timestamp"],
                content_hash=body_hash,
            )

        # Check canonical payloads json fallback
        canonical = _load_canonical_data()
        example_source = canonical.get("source_response")
        if example_source and example_source.get("id") == source_id:
            return SourceResponse(**example_source)

        raise EntityNotFoundError(f"Source with id '{source_id}' was not found.")

    async def get_history(self, work_item_id: str) -> WorkItemHistoryResponse:
        """Fetch accepted forecast cutover history for a work item."""
        current_version = get_active_evidence_version()
        repo = get_graph_repository()

        if repo is not None:
            try:
                raw_history = await asyncio.to_thread(repo.get_history, work_item_id)
                if raw_history is None:
                    raise EntityNotFoundError(f"Work item '{work_item_id}' not found.")
                if isinstance(raw_history, dict):
                    return WorkItemHistoryResponse(**raw_history)
                return raw_history
            except EntityNotFoundError:
                raise
            except Exception as exc:
                logger.error("Error retrieving history for %s: %s", work_item_id, exc)
                settings = get_settings()
                if not settings.dev_mocks:
                    raise GraphUnavailableError(f"Error querying history for '{work_item_id}': {exc}") from exc

        # Fallback / mock mode
        # Canonical baseline for wi_permissions with non-nullable decision_id DEC-12
        if work_item_id == "wi_permissions":
            return WorkItemHistoryResponse(
                evidence_version=current_version,
                forecasts=[
                    ForecastHistoryItem(
                        id="fc_perm_baseline",
                        available_at=1792605599999,  # October 21, 2026
                        valid_from=1790000000000,
                        valid_to=None,
                        decision_id="DEC-12",
                        citations=[SourceRef(source_id="src_permissions_ticket", quote="October 21, 2026")],
                    )
                ],
            )

        if work_item_id in ("wi_sso", "wi_identity_migration", "wi_audit", "wi_export", "wi_export_worker"):
            return WorkItemHistoryResponse(
                evidence_version=current_version,
                forecasts=[
                    ForecastHistoryItem(
                        id=f"fc_{work_item_id}_baseline",
                        available_at=1792605599999,
                        valid_from=1790000000000,
                        valid_to=None,
                        decision_id=f"dec_baseline_{work_item_id}",
                        citations=[SourceRef(source_id=f"src_{work_item_id}_plan", quote=f"Accepted baseline forecast for {work_item_id}.")],
                    )
                ],
            )

        raise EntityNotFoundError(f"Work item with id '{work_item_id}' was not found.")
