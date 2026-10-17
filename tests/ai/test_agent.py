"""Unit tests for bounded AI Agent across impact/owners and lineage questions."""

import pytest

from backend.app.ai.agent import (
    StaleEvidenceError,
    run_agent,
)
from backend.app.ai.provider import (
    DeterministicTestDouble,
)
from backend.app.ai.tools import AgentTools
from backend.app.schemas import AgentRunRequest


class AgentTestRepo:
    def __init__(self, version: str = "ds_demo_20261017:rev_2"):
        self.version = version
        self.sources = {
            "src_permissions_ticket": {
                "id": "src_permissions_ticket",
                "body": (
                    "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
                    "Owner: Priya. This replaces decision DEC-12."
                ),
            },
            "src_acme_handoff": {
                "id": "src_acme_handoff",
                "body": "Commitment: Enterprise SSO delivered by October 23, 2026.",
            },
            "src_cedar_handoff": {
                "id": "src_cedar_handoff",
                "body": "Commitment: Data export delivered by October 23, 2026.",
            },
            "src_dec12": {
                "id": "src_dec12",
                "body": "Approved. The permissions service will be delivered by October 21, 2026. Owner: Priya.",
            },
        }

    def get_version(self) -> str:
        return self.version

    def get_source(self, source_id: str) -> dict:
        if source_id in self.sources:
            return self.sources[source_id]
        raise KeyError(f"Source {source_id} not found")

    def get_history(self, work_item_id: str) -> dict:
        return {
            "evidence_version": self.version,
            "forecasts": [
                {
                    "id": "fc_permissions_v1",
                    "available_at": 1792607399999,  # 2026-10-21
                    "valid_from": 1792153800000,
                    "valid_to": 1792240151000,
                    "decision_id": "DEC-12",
                    "supersedes_id": None,
                    "decision_summary": "Initial permissions milestone",
                    "citations": [{"source_id": "src_dec12", "quote": "Approved. The permissions service will be delivered by October 21, 2026. Owner: Priya."}],
                },
                {
                    "id": "fc_permissions_v2",
                    "available_at": 1793212199999,  # 2026-10-28
                    "valid_from": 1792240151000,
                    "valid_to": None,
                    "decision_id": "dec_live_permissions_001",
                    "supersedes_id": "DEC-12",
                    "decision_summary": "Permissions delivery rescheduled to Oct 28",
                    "citations": [{"source_id": "src_permissions_ticket", "quote": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12."}],
                },
            ],
        }

    def list_impacts(self, as_of_ms: int | None = None) -> dict:
        return {
            "evidence_version": self.version,
            "as_of": as_of_ms or 1792240151000,
            "impacts": [
                {
                    "commitment_id": "com_acme_sso",
                    "customer": {"id": "cust_acme", "name": "Acme Corp"},
                    "title": "Enterprise SSO Integration",
                    "due_at": 1792780199999,  # 2026-10-23
                    "status": "date_conflict",
                    "reasons": ["Blocker wi_permissions is due after Oct 23"],
                    "blockers": [
                        {
                            "work_item_id": "wi_permissions",
                            "name": "Permissions Service",
                            "forecast_id": "fc_permissions_v2",
                            "available_at": 1793212199999,  # 2026-10-28
                            "decision_id": "dec_live_permissions_001",
                        }
                    ],
                    "paths": [],
                    "engineering_owner": {"id": "person_priya", "name": "Priya Sharma"},
                    "account_owner": {"id": "person_maya", "name": "Maya Patel"},
                    "citations": [
                        {"source_id": "src_permissions_ticket", "quote": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12."},
                        {"source_id": "src_acme_handoff", "quote": "Commitment: Enterprise SSO delivered by October 23, 2026."},
                    ],
                },
                {
                    "commitment_id": "com_cedar_export",
                    "customer": {"id": "cust_cedar", "name": "Cedar Technologies"},
                    "title": "Automated Data Export Service",
                    "due_at": 1792780199999,  # 2026-10-23
                    "status": "no_detected_conflict",
                    "reasons": [],
                    "blockers": [],
                    "paths": [],
                    "engineering_owner": {"id": "person_eli", "name": "Eli Vance"},
                    "account_owner": {"id": "person_leo", "name": "Leo Chen"},
                    "citations": [
                        {"source_id": "src_cedar_handoff", "quote": "Commitment: Data export delivered by October 23, 2026."}
                    ],
                },
                {
                    "commitment_id": "com_incomplete",
                    "customer": {"id": "cust_incomplete", "name": "Incomplete Inc"},
                    "title": "Unassigned Feature",
                    "due_at": 1792780199999,
                    "status": "needs_verification",
                    "reasons": ["missing_engineering_owner: no owner recorded for wi_unknown"],
                    "blockers": [],
                    "paths": [],
                    "engineering_owner": None,
                    "account_owner": {"id": "person_maya", "name": "Maya Patel"},
                    "citations": [],
                },
            ],
            "completeness": {"complete": True, "truncated": False, "warnings": []},
        }

    def get_evidence(self, commitment_id: str, as_of_ms: int | None = None) -> dict:
        for imp in self.list_impacts(as_of_ms)["impacts"]:
            if imp["commitment_id"] == commitment_id:
                return imp
        return {}

    def get_owners(self, commitment_id: str, as_of_ms: int | None = None) -> dict:
        ev = self.get_evidence(commitment_id, as_of_ms)
        return {
            "engineering_owner": ev.get("engineering_owner"),
            "account_owner": ev.get("account_owner"),
            "warnings": [],
        }

    def resolve_entity(self, query: str, kind: str | None = None) -> list:
        if "acme" in query.lower():
            return [{"id": "cust_acme", "kind": "customer", "name": "Acme Corp"}]
        if "cedar" in query.lower():
            return [{"id": "cust_cedar", "kind": "customer", "name": "Cedar Technologies"}]
        if "permissions" in query.lower():
            return [{"id": "wi_permissions", "kind": "work_item", "name": "Permissions Service"}]
        return []


@pytest.mark.asyncio
async def test_agent_impact_and_owners_acme_conflict():
    """Agent answers impact for Acme SSO: states due date vs forecast date, resolves owners, and produces cited drafts."""
    repo = AgentTestRepo()
    req = AgentRunRequest(
        message="What is the impact of permissions delay on Acme?",
        commitment_id="com_acme_sso",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo)

    assert res.status == "complete"
    assert res.evidence_version == repo.version
    assert "Acme Corp" in res.answer
    assert "2026-10-23" in res.answer  # Promise due date
    assert "2026-10-28" in res.answer  # Revised forecast date
    assert "Priya Sharma" in res.answer
    assert "Maya Patel" in res.answer
    assert "replanning" in res.answer

    # Citations must be populated and verified (not dropped!)
    assert len(res.citations) > 0
    assert any(c.source_id == "src_permissions_ticket" for c in res.citations)

    # Verify drafts
    assert len(res.drafts) == 2
    esc_draft = next(d for d in res.drafts if d.kind == "internal_escalation")
    assert esc_draft.assignee_id == "person_priya"
    assert "dec_live_permissions_001" in esc_draft.based_on_decision_ids
    # Drafts MUST have verified citations
    assert len(esc_draft.citations) > 0

    cust_draft = next(d for d in res.drafts if d.kind == "customer_update")
    assert cust_draft.assignee_id == "person_maya"
    assert len(cust_draft.citations) > 0

    # Verify tool trace shows genuine tool calling: resolve_entity was called
    assert len(res.tool_trace) <= 6
    assert any(t.tool == "resolve_entity" for t in res.tool_trace)
    assert any(t.tool == "get_evidence" for t in res.tool_trace)


@pytest.mark.asyncio
async def test_agent_lineage_question():
    """Agent answers 'Why did the permissions forecast change?' using DEC-12 lineage and exact quotes."""
    repo = AgentTestRepo()
    req = AgentRunRequest(
        message="Why did the permissions forecast change from DEC-12?",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo)

    assert res.status == "complete"
    assert "2026-10-21" in res.answer
    assert "2026-10-28" in res.answer
    assert "DEC-12" in res.answer
    assert "dec_live_permissions_001" in res.answer
    assert "Recorded vs. Inferred Facts" in res.answer

    # Followed establishing decision to get_source
    assert any(t.tool == "get_forecast_history" for t in res.tool_trace)
    assert any(t.tool == "get_source" for t in res.tool_trace)


@pytest.mark.asyncio
async def test_agent_completeness_warning_surfaced_for_selected_commitment():
    """When a selected commitment has status needs_verification, agent returns partial status and surfaces reasons."""
    repo = AgentTestRepo()
    req = AgentRunRequest(
        message="What is the status of Incomplete Inc commitment?",
        commitment_id="com_incomplete",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo)

    assert res.status == "partial"
    assert any("missing_engineering_owner" in w for w in res.warnings)


@pytest.mark.asyncio
async def test_agent_unknown_customer_resolution():
    """Agent resolves entity via resolve_entity and reports if customer is unknown."""
    repo = AgentTestRepo()
    req = AgentRunRequest(
        message="Which commitments are affected by the Globex delay?",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo)

    assert any(t.tool == "resolve_entity" and t.arguments.get("query") == "Globex" for t in res.tool_trace)
    assert "not found" in res.answer.lower() or "no commitments" in res.answer.lower()


@pytest.mark.asyncio
async def test_agent_stale_evidence_version_rejected():
    """Agent rejects stale evidence_version with StaleEvidenceError (maps to 409)."""
    repo = AgentTestRepo(version="ds_demo_20261017:rev_2")
    req = AgentRunRequest(
        message="Impact on Acme?",
        expected_version="ds_demo_20261017:rev_1",  # Stale!
    )
    with pytest.raises(StaleEvidenceError) as exc_info:
        await run_agent(request=req, tools=repo)
    assert exc_info.value.expected == "ds_demo_20261017:rev_1"
    assert exc_info.value.current == "ds_demo_20261017:rev_2"


@pytest.mark.asyncio
async def test_agent_control_customer_no_conflict():
    """Cedar Technologies shows no detected conflict."""
    repo = AgentTestRepo()
    req = AgentRunRequest(
        message="What is the status for Cedar export?",
        commitment_id="com_cedar_export",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo)

    assert res.status == "complete"
    assert "no detected date conflict" in res.answer
    assert len(res.drafts) == 0


@pytest.mark.asyncio
async def test_agent_with_provider_timeout_fallback_preserves_citations():
    """If provider times out during generation, agent falls back to grounded partial answer with citations."""
    repo = AgentTestRepo()
    timeout_provider = DeterministicTestDouble(force_timeout=True)
    req = AgentRunRequest(
        message="Acme impact status?",
        commitment_id="com_acme_sso",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=repo, provider=timeout_provider)

    assert res.status == "partial"
    assert any("timed out" in w for w in res.warnings)
    assert "Acme Corp" in res.answer
    assert "Priya Sharma" in res.answer


@pytest.mark.asyncio
async def test_agent_strictly_respects_tool_budget():
    """Agent respects tool call limit of 6."""
    repo = AgentTestRepo()
    tool_runner = AgentTools(repo=repo)
    # Exhaust 5 calls
    for _ in range(5):
        tool_runner.get_source("src_permissions_ticket")

    req = AgentRunRequest(
        message="Acme status?",
        commitment_id="com_acme_sso",
        expected_version="ds_demo_20261017:rev_2",
    )
    res = await run_agent(request=req, tools=tool_runner)
    assert len(tool_runner.trace) <= 6
    assert res.status in ("complete", "partial")
