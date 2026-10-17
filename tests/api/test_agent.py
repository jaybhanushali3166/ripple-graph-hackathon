"""Dedicated unit tests for /api/agent/run endpoint.

Tests cover:
- Question Type 1: Affected commitments and owners (Acme SSO, Priya Sharma, Maya Lin)
- Question Type 2: Decision lineage and historical context (DEC-12, 7-day shift)
- Tool trace assertions (tool name, arguments, evidence IDs, status)
- Draft follow-up action formats (internal escalation, customer update)
- Stale evidence version rejection (409 stale_evidence)
- Request validation and error envelopes (422 invalid_input)
- Direct AgentTools unit tests (resolve_entity, find_impacted_commitments, get_evidence, get_forecast_history)
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.agent_service import AgentTools

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_to_clean_state():
    """Reset demo state before each test to ensure isolated dataset and revision."""
    client.post("/api/demo/reset")


def test_agent_run_impact_and_owners_query():
    """Question Type 1: Query affected promises and owners for Acme SSO."""
    active_version = client.get("/api/impacts").json()["evidence_version"]

    response = client.post(
        "/api/agent/run",
        json={
            "message": "Which commitments are impacted and who are the responsible owners?",
            "commitment_id": "com_acme_sso",
            "expected_version": active_version,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "complete"
    assert data["evidence_version"] == active_version
    assert "run_id" in data
    assert data["run_id"].startswith("run_")

    # Answer assertions
    answer = data["answer"]
    assert "Acme" in answer
    assert "Priya Sharma" in answer
    assert "Maya Lin" in answer

    # Citations assertions
    assert len(data["citations"]) >= 1
    citation_sources = {c["source_id"] for c in data["citations"]}
    assert "src_permissions_ticket" in citation_sources or "src_acme_handoff" in citation_sources

    # Tool trace assertions
    assert len(data["tool_trace"]) >= 1
    tool_names = [t["tool"] for t in data["tool_trace"]]
    assert "resolve_entity" in tool_names or "find_impacted_commitments" in tool_names
    for trace_item in data["tool_trace"]:
        assert trace_item["status"] == "ok"
        assert isinstance(trace_item["arguments"], dict)
        assert isinstance(trace_item["evidence_ids"], list)

    # Drafts assertions
    assert len(data["drafts"]) >= 1
    draft_kinds = {d["kind"] for d in data["drafts"]}
    assert "internal_escalation" in draft_kinds or "customer_update" in draft_kinds
    for draft in data["drafts"]:
        assert draft["commitment_id"] == "com_acme_sso"
        assert draft["assignee_id"] in ("person_priya", "person_maya")
        assert len(draft["body"]) > 0
        assert len(draft["citations"]) >= 1
        assert len(draft["based_on_decision_ids"]) >= 1


def test_agent_run_decision_lineage_query():
    """Question Type 2: Query why permissions forecast shifted and DEC-12 lineage."""
    active_version = client.get("/api/impacts").json()["evidence_version"]

    response = client.post(
        "/api/agent/run",
        json={
            "message": "Why did the permissions forecast change from DEC-12?",
            "commitment_id": "com_acme_sso",
            "expected_version": active_version,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "complete"
    assert "DEC-12" in data["answer"]
    assert "October 21" in data["answer"]
    assert "October 28" in data["answer"]

    # Tool trace assertions for lineage query
    tool_names = [t["tool"] for t in data["tool_trace"]]
    assert "get_forecast_history" in tool_names
    history_trace = next(t for t in data["tool_trace"] if t["tool"] == "get_forecast_history")
    assert history_trace["arguments"]["work_item_id"] == "wi_permissions"
    assert "DEC-12" in history_trace["evidence_ids"]

    # Citations assert DEC-12 presence
    assert any("DEC-12" in c["quote"] for c in data["citations"])

    # Draft follow-up assertions
    assert len(data["drafts"]) >= 1
    assert any("DEC-12" in d["based_on_decision_ids"] for d in data["drafts"])


def test_agent_run_stale_expected_version():
    """Verify agent run rejects mismatched expected_version with 409 stale_evidence."""
    response = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact on Acme?",
            "expected_version": "ds_outdated_version:rev_0",
        },
    )
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "stale_evidence"
    assert "stale" in data["error"]["message"].lower()


def test_agent_run_schema_validation_missing_message():
    """Verify agent run rejects missing message or empty body with 422 invalid_input."""
    res1 = client.post("/api/agent/run", json={})
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "invalid_input"

    res2 = client.post("/api/agent/run", json={"expected_version": "ds_1:rev_1"})
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "invalid_input"


def test_agent_tools_unit():
    """Directly test AgentTools methods: resolve_entity, find_impacted_commitments, get_evidence, get_forecast_history."""
    async def _run():
        tools = AgentTools()

        # resolve_entity
        acme_entity = await tools.resolve_entity("Acme")
        assert acme_entity["id"] == "com_acme_sso"

        priya_entity = await tools.resolve_entity("Priya")
        assert priya_entity["id"] == "person_priya"

        perm_entity = await tools.resolve_entity("Permissions")
        assert perm_entity["id"] == "wi_permissions"

        unknown_entity = await tools.resolve_entity("nonexistent_xyz")
        assert "error" in unknown_entity

        # find_impacted_commitments
        impacts = await tools.find_impacted_commitments()
        assert isinstance(impacts, list)
        assert len(impacts) == 4

        # get_evidence
        evidence = await tools.get_evidence("src_permissions_ticket")
        assert evidence["id"] == "src_permissions_ticket"
        assert "October 21, 2026" in evidence["body"]
        assert "DEC-12" in evidence["body"]

        # get_forecast_history
        history = await tools.get_forecast_history("wi_permissions")
        assert "forecasts" in history
        assert len(history["forecasts"]) >= 1
        assert history["forecasts"][0]["decision_id"] == "DEC-12"

    import asyncio
    asyncio.run(_run())
