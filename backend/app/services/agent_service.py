"""Agent orchestration service supporting two bounded question types: impact/owners and lineage."""

import asyncio
import logging
import time
from typing import Optional

from backend.app.ai.agent import _default_tool_step_handler, run_agent
from backend.app.ai.tools import AgentTools
from backend.app.ai.provider import (
    DeterministicTestDouble,
    LLMProvider,
    get_provider,
)
from backend.app.graph.errors import StaleEvidence
from backend.app.schemas import (
    AgentResponse,
    AgentRunRequest,
    Completeness,
    Draft,
    SourceRef,
    ToolTraceItem,
)
from backend.app.services.demo_service import get_active_evidence_version
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.agent_service")


class AgentService:
    """Service orchestrating agent runs with bounded question classification and tool tracing."""

    async def run_agent(self, request: AgentRunRequest) -> AgentResponse:
        """Execute agent analysis under strict version validation and bounded tool access."""
        repo = get_graph_repository()
        now_ms = int(time.time() * 1000)
        settings = get_settings()

        if repo is not None:
            # 1. Version check before starting
            current_version = repo.get_version()
            if request.expected_version != current_version:
                raise StaleEvidence(
                    f"evidence version is {current_version}, not {request.expected_version}",
                    details={"current_version": current_version},
                )

            # 2. Configure provider
            if settings.llm_api_key:
                provider: LLMProvider = get_provider(
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                )
            else:
                provider = DeterministicTestDouble(tool_step_handler=_default_tool_step_handler)

            # 3. Execute bounded agent orchestrator with repo as tools
            response = await run_agent(
                request=request,
                tools=repo,
                provider=provider,
                now_ms=now_ms,
            )

            # 4. Spec requirement: Recheck version before returning drafts
            post_run_version = repo.get_version()
            if post_run_version != current_version:
                logger.warning(
                    "Evidence version changed during agent run from %s to %s; invalidating drafts.",
                    current_version,
                    post_run_version,
                )
                response.drafts = []
                response.status = "partial"
                response.warnings.append(
                    f"Evidence version moved to '{post_run_version}' during reasoning; drafts invalidated."
                )

            return response

        # Mock fallback (only when repo is None / DEV_MOCKS=True)
        active_version = get_active_evidence_version()
        if request.expected_version != active_version:
            raise StaleEvidence(
                f"Provided expected_version '{request.expected_version}' is stale. Active evidence version is {active_version}.",
                details={"current_version": active_version},
            )

        is_lineage = any(k in request.message.lower() for k in ["lineage", "dec-12", "why", "shift"])
        if is_lineage:
            answer = (
                "The permissions forecast changed from DEC-12 to DEC-13. "
                "Delivery moves from October 21, 2026 to October 28, 2026. "
                "Responsible engineering owner: Priya Sharma."
            )
            citations = [
                SourceRef(
                    source_id="src_permissions_ticket",
                    quote="Forecast: permissions service available October 21, 2026 (see DEC-12).",
                ),
                SourceRef(
                    source_id="src_dec12",
                    quote="The permissions service will be delivered by October 21, 2026. Owner: Priya.",
                ),
            ]
            tool_trace = [
                ToolTraceItem(
                    tool="get_forecast_history",
                    arguments={"work_item_id": "wi_permissions"},
                    evidence_ids=["DEC-12", "DEC-13"],
                    status="ok",
                ),
                ToolTraceItem(
                    tool="get_source",
                    arguments={"source_id": "src_permissions_ticket"},
                    evidence_ids=["src_permissions_ticket"],
                    status="ok",
                ),
            ]
            drafts = [
                Draft(
                    kind="internal_escalation",
                    commitment_id=request.commitment_id or "com_acme_sso",
                    assignee_id="person_priya",
                    body="Permissions delivery has shifted from October 21 to October 28, impacting customer milestones.",
                    citations=[
                        SourceRef(
                            source_id="src_permissions_ticket",
                            quote="delivery moves from October 21, 2026 to October 28, 2026",
                        )
                    ],
                    based_on_decision_ids=["DEC-12"],
                )
            ]
        else:
            answer = (
                "Commitment com_acme_sso for customer Acme Corp is in date conflict due to permissions service delay. "
                "Accountable engineering owner is Priya Sharma. Account owner is Maya Lin."
            )
            citations = [
                SourceRef(
                    source_id="src_permissions_ticket",
                    quote="delivery moves from October 21, 2026 to October 28, 2026",
                ),
                SourceRef(
                    source_id="src_acme_handoff",
                    quote="Commitment: Enterprise SSO delivered by October 23, 2026.",
                ),
            ]
            tool_trace = [
                ToolTraceItem(
                    tool="resolve_entity",
                    arguments={"query": "Acme", "kind": "customer"},
                    evidence_ids=["cust_acme"],
                    status="ok",
                ),
                ToolTraceItem(
                    tool="find_impacted_commitments",
                    arguments={},
                    evidence_ids=["com_acme_sso", "com_birch_audit"],
                    status="ok",
                ),
                ToolTraceItem(
                    tool="get_evidence",
                    arguments={"commitment_id": "com_acme_sso"},
                    evidence_ids=["src_permissions_ticket"],
                    status="ok",
                ),
            ]
            drafts = [
                Draft(
                    kind="internal_escalation",
                    commitment_id="com_acme_sso",
                    assignee_id="person_priya",
                    body="Priya: Acme SSO is promised for Oct 23. The permissions service delay to Oct 28 causes a date conflict.",
                    citations=[
                        SourceRef(
                            source_id="src_permissions_ticket",
                            quote="delivery moves from October 21, 2026 to October 28, 2026",
                        )
                    ],
                    based_on_decision_ids=["DEC-12"],
                ),
                Draft(
                    kind="customer_update",
                    commitment_id="com_acme_sso",
                    assignee_id="person_maya",
                    body="Acme Corp update: Enterprise SSO integration timeline is currently being reviewed with engineering.",
                    citations=[
                        SourceRef(
                            source_id="src_acme_handoff",
                            quote="Commitment: Enterprise SSO delivered by October 23, 2026.",
                        )
                    ],
                    based_on_decision_ids=["DEC-12"],
                ),
            ]

        return AgentResponse(
            run_id=f"run_mock_{int(time.time() * 1000)}",
            evidence_version=active_version,
            status="complete",
            answer=answer,
            citations=citations,
            drafts=drafts,
            tool_trace=tool_trace,
            warnings=[],
        )
