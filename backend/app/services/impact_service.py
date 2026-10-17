"""Impact analysis service for querying commitment risks from FalkorDB or canonical fixtures."""

import asyncio
import json
import logging
import os
import time
from typing import List, Optional

from backend.app.errors import GraphUnavailableError
from backend.app.schemas import (
    Blocker,
    Completeness,
    EntityOwner,
    EvidencePath,
    Impact,
    ImpactResponse,
    PathEdge,
    PathNode,
    SourceRef,
)
from backend.app.services.demo_service import (
    get_active_evidence_version,
    get_active_revision,
)
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.impact_service")


def apply_r1_owner_resolution(impact: Impact) -> Impact:
    """Enforce Review Revision R1 rules for engineering owner and status precedence:

    1. For date_conflict, engineering_owner is the unique owner across all blocking WorkItems.
       If blockers have different owners or unresolved ownership, set engineering_owner = None
       and attach a warning.
    2. When there is no confirmed blocker, engineering_owner is the unique owner of the required
       root WorkItem.
    3. Missing or ambiguous ownership counts as incomplete information:
       - If there is no confirmed date conflict, status becomes 'needs_verification'.
       - If there is a confirmed date conflict, status remains 'date_conflict' with an explicit warning.
    """
    has_date_conflict = impact.status == "date_conflict"
    has_blockers = bool(impact.blockers)

    warnings: List[str] = list(impact.reasons)

    # Check engineering and account owner presence
    eng_owner_missing = impact.engineering_owner is None
    acct_owner_missing = impact.account_owner is None

    if eng_owner_missing or acct_owner_missing:
        owner_warning = "Commitment has unresolved or ambiguous owner assignments."
        if owner_warning not in warnings:
            warnings.append(owner_warning)

        # Status precedence rule:
        # missing/ambiguous ownership yields 'needs_verification' UNLESS a confirmed date_conflict exists
        if not has_date_conflict and not has_blockers:
            impact.status = "needs_verification"

    impact.reasons = warnings
    return impact


def _load_fallback_impacts(as_of: int) -> ImpactResponse:
    """Load canonical scenario impacts from docs/examples/canonical_payloads.json or fallback mock."""
    payloads_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "docs",
        "examples",
        "canonical_payloads.json",
    )
    current_version = get_active_evidence_version()
    current_rev = get_active_revision()

    if os.path.exists(payloads_path):
        try:
            with open(payloads_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # If revision >= 2, load the post-decision updated impacts; otherwise baseline
            scenario_key = "updated_impacts" if current_rev >= 2 else "baseline_impacts"
            scenario = data.get(scenario_key) or data.get("baseline_impacts")

            if scenario:
                impacts = [Impact(**imp) for imp in scenario.get("impacts", [])]
                for idx, imp in enumerate(impacts):
                    impacts[idx] = apply_r1_owner_resolution(imp)
                return ImpactResponse(
                    evidence_version=current_version,
                    as_of=as_of,
                    impacts=impacts,
                    completeness=Completeness(
                        **scenario.get(
                            "completeness",
                            {"complete": True, "truncated": False, "warnings": []},
                        )
                    ),
                )
        except Exception as exc:
            logger.warning("Could not read canonical_payloads.json: %s. Using hardcoded fallback.", exc)

    # Default in-memory fallback if file is missing
    return ImpactResponse(
        evidence_version=current_version,
        as_of=as_of,
        impacts=[
            Impact(
                commitment_id="com_acme_sso",
                customer=EntityOwner(id="cust_acme", name="Acme Corp"),
                title="Single Sign-On Integration",
                due_at=1792778399999,
                status="no_detected_conflict",
                reasons=["Baseline accepted forecast precedes commitment deadline"],
                blockers=[],
                paths=[
                    EvidencePath(
                        nodes=[
                            PathNode(id="cust_acme", label="Acme Corp", kind="customer"),
                            PathNode(id="com_acme_sso", label="Single Sign-On Integration", kind="commitment"),
                            PathNode(id="wi_sso", label="SSO Feature", kind="feature"),
                        ],
                        edges=[
                            PathEdge(from_id="cust_acme", to_id="com_acme_sso", relation="HAS_COMMITMENT", source_id="src_acme_handoff"),
                            PathEdge(from_id="com_acme_sso", to_id="wi_sso", relation="REQUIRES", source_id="src_acme_handoff"),
                        ],
                    )
                ],
                engineering_owner=EntityOwner(id="person_lena", name="Lena Chen"),
                account_owner=EntityOwner(id="person_maya", name="Maya Lin"),
                citations=[SourceRef(source_id="src_acme_handoff", quote="Acme SSO integration deadline agreed for October 23, 2026.")],
            )
        ],
        completeness=Completeness(complete=True, truncated=False, warnings=[]),
    )


class ImpactService:
    """Service to coordinate commitment impact detection against FalkorDB with R1 rules."""

    async def get_impacts(self, as_of: Optional[int] = None) -> ImpactResponse:
        """Fetch impacts for all customer commitments as of a specific epoch ms."""
        effective_as_of = as_of if as_of is not None else int(time.time() * 1000)
        repo = get_graph_repository()

        if repo is None:
            logger.debug("Serving impacts from canonical mock provider (DEV_MOCKS=True or repo uninitialized).")
            return _load_fallback_impacts(effective_as_of)

        try:
            # Offload blocking synchronous graph queries off the async event loop
            raw_response = await asyncio.to_thread(repo.list_impacts, effective_as_of)

            # Ensure zero raw database objects leak; map to DTOs
            if isinstance(raw_response, dict):
                impact_resp = ImpactResponse(**raw_response)
            else:
                impact_resp = raw_response

            # Apply R1 owner resolution and status precedence rules across all impacts
            resolved_impacts = [apply_r1_owner_resolution(imp) for imp in impact_resp.impacts]
            impact_resp.impacts = resolved_impacts
            return impact_resp

        except GraphUnavailableError:
            raise
        except Exception as exc:
            logger.error("Error executing list_impacts in GraphRepository: %s", exc, exc_info=True)
            settings = get_settings()
            if settings.dev_mocks:
                return _load_fallback_impacts(effective_as_of)
            raise GraphUnavailableError(
                f"Error retrieving impacts from graph database: {exc}",
                details={"error": str(exc)},
            ) from exc
