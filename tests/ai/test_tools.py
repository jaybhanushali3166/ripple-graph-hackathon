"""Unit tests for AgentTools wrapper, 6-call budget limit, and trace logging."""

import pytest

from backend.app.ai.tools import (
    MAX_TOOL_CALLS,
    AgentTools,
    ToolBudgetExceededError,
)


class MockGraphRepository:
    """Mock repository matching GraphRepositoryProtocol."""

    def __init__(self):
        self.version = "ds_demo_001:rev_1"

    def get_version(self) -> str:
        return self.version

    def get_source(self, source_id: str) -> dict:
        return {
            "id": source_id,
            "type": "ticket",
            "title": "Permissions Ticket",
            "body": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026.",
            "source_timestamp": 1792153800000,
            "content_hash": "sha256:abc",
        }

    def get_history(self, work_item_id: str) -> dict:
        return {
            "evidence_version": self.version,
            "forecasts": [
                {
                    "id": "fc_perm_v1",
                    "available_at": 1792607399999,
                    "valid_from": 1792153800000,
                    "valid_to": 1792240151000,
                    "decision_id": "DEC-12",
                    "citations": [{"source_id": "src_dec12", "quote": "permissions delivery committed"}],
                },
                {
                    "id": "fc_perm_v2",
                    "available_at": 1793212199999,
                    "valid_from": 1792240151000,
                    "valid_to": None,
                    "decision_id": "dec_live_permissions_001",
                    "citations": [{"source_id": "src_ticket", "quote": "moves to October 28, 2026"}],
                },
            ],
        }

    def list_impacts(self, as_of_ms: int | None) -> dict:
        return {
            "evidence_version": self.version,
            "as_of": as_of_ms or 1792240151000,
            "impacts": [
                {
                    "commitment_id": "com_acme_sso",
                    "customer": {"id": "cust_acme", "name": "Acme Corp"},
                    "title": "Enterprise SSO Integration",
                    "due_at": 1792780199999,
                    "status": "date_conflict",
                    "reasons": ["Blocker wi_permissions is due after Oct 23"],
                    "blockers": [
                        {
                            "work_item_id": "wi_permissions",
                            "name": "Permissions Service",
                            "forecast_id": "fc_perm_v2",
                            "available_at": 1793212199999,
                            "decision_id": "dec_live_permissions_001",
                        }
                    ],
                    "paths": [],
                    "engineering_owner": {"id": "person_priya", "name": "Priya Sharma"},
                    "account_owner": {"id": "person_maya", "name": "Maya Patel"},
                    "citations": [{"source_id": "src_ticket", "quote": "moves to October 28, 2026"}],
                }
            ],
            "completeness": {"complete": True, "truncated": False, "warnings": []},
        }

    def get_evidence(self, commitment_id: str, as_of_ms: int | None) -> dict:
        impacts = self.list_impacts(as_of_ms)["impacts"]
        for imp in impacts:
            if imp["commitment_id"] == commitment_id:
                return imp
        return {}

    def get_owners(self, commitment_id: str, as_of_ms: int | None) -> dict:
        evidence = self.get_evidence(commitment_id, as_of_ms)
        return {
            "engineering_owner": evidence.get("engineering_owner"),
            "account_owner": evidence.get("account_owner"),
            "warnings": [],
        }

    def resolve_entity(self, query: str, kind: str | None = None) -> list[dict]:
        if "acme" in query.lower():
            return [{"id": "cust_acme", "kind": "customer", "name": "Acme Corp"}]
        if "priya" in query.lower():
            return [{"id": "person_priya", "kind": "person", "name": "Priya Sharma"}]
        return []


def test_agent_tools_operations():
    """AgentTools successfully delegates to repository and records structured trace."""
    repo = MockGraphRepository()
    tools = AgentTools(repo=repo)

    # 1. resolve_entity
    entities = tools.resolve_entity("Acme")
    assert len(entities) == 1
    assert entities[0]["id"] == "cust_acme"
    assert tools.call_count == 1
    assert tools.trace[-1].tool == "resolve_entity"
    assert tools.trace[-1].evidence_ids == ["cust_acme"]
    assert tools.trace[-1].status == "ok"

    # 2. find_impacted_commitments
    impacts_res = tools.find_impacted_commitments()
    assert len(impacts_res["impacts"]) == 1
    assert tools.call_count == 2
    assert tools.trace[-1].tool == "find_impacted_commitments"
    assert tools.trace[-1].evidence_ids == ["com_acme_sso"]
    # Check that citations are kept in citations, not overwriting full sources
    assert len(tools.accumulated_evidence["citations"]) > 0

    # 3. get_evidence
    evidence = tools.get_evidence("com_acme_sso")
    assert evidence["commitment_id"] == "com_acme_sso"
    assert tools.call_count == 3
    assert tools.trace[-1].tool == "get_evidence"

    # 4. get_owners
    owners = tools.get_owners("com_acme_sso")
    assert owners["engineering_owner"]["id"] == "person_priya"
    assert tools.call_count == 4
    assert tools.trace[-1].tool == "get_owners"

    # 5. get_forecast_history
    history = tools.get_forecast_history("wi_permissions")
    assert len(history["forecasts"]) == 2
    assert tools.call_count == 5
    assert tools.trace[-1].tool == "get_forecast_history"

    # 6. get_source
    source = tools.get_source("src_permissions_ticket")
    assert source["id"] == "src_permissions_ticket"
    assert tools.call_count == 6
    assert tools.trace[-1].tool == "get_source"
    # Full body preserved in sources cache
    assert "body" in tools.accumulated_evidence["sources"]["src_permissions_ticket"]


def test_agent_tools_strictly_enforces_six_call_budget():
    """AgentTools raises ToolBudgetExceededError on the 7th call."""
    repo = MockGraphRepository()
    tools = AgentTools(repo=repo)

    assert MAX_TOOL_CALLS == 6
    for i in range(6):
        tools.get_source(f"src_{i}")
    assert tools.call_count == 6

    # 7th call should raise ToolBudgetExceededError
    with pytest.raises(ToolBudgetExceededError) as exc_info:
        tools.get_source("src_7")
    assert "exceeded maximum tool call budget" in str(exc_info.value)
    assert len(tools.warnings) > 0


def test_tool_trace_excludes_private_chain_of_thought():
    """Tool trace records tool name, args, evidence IDs, and status only."""
    repo = MockGraphRepository()
    tools = AgentTools(repo=repo)

    tools.resolve_entity("Priya", kind="person")
    trace_item = tools.trace[0]
    trace_dict = trace_item.model_dump()

    assert set(trace_dict.keys()) == {"tool", "arguments", "evidence_ids", "status"}
    assert "thought" not in trace_dict
    assert "chain_of_thought" not in trace_dict
