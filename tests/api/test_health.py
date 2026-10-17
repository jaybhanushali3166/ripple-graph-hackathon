"""Tests for health check, error envelope formats, and impact endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_get_health():
    """Verify GET /api/health returns HTTP 200 and expected status/database/version."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "ok",
        "database": "falkordb",
        "version": "0.1.0",
    }


def test_404_error_envelope():
    """Verify non-existent routes return HTTP 404 in the unified Ripple error envelope."""
    response = client.get("/api/nonexistent-endpoint-404")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "http_error"
    assert data["error"]["message"] == "Not Found"
    assert data["error"]["details"] is None


def test_validation_error_envelope():
    """Verify request validation failures return HTTP 422 with invalid_input code."""
    # POST to /api/decisions/confirm without required fields
    response = client.post("/api/decisions/confirm", json={})
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_input"
    assert data["error"]["message"] == "Request validation failed"
    assert isinstance(data["error"]["details"], list)
    assert len(data["error"]["details"]) > 0


def test_mock_get_impacts():
    """Verify GET /api/impacts returns canonical 4-customer impact payload with complete metadata."""
    response = client.get("/api/impacts")
    assert response.status_code == 200
    assert response.headers.get("x-mock-mode") == "true"

    data = response.json()
    assert "evidence_version" in data
    assert "as_of" in data
    assert isinstance(data["as_of"], int)

    # Verify completeness metadata
    assert "completeness" in data
    completeness = data["completeness"]
    assert completeness["complete"] is True
    assert completeness["truncated"] is False
    assert completeness["warnings"] == []

    # Verify canonical 4 commitments
    impacts = data.get("impacts", [])
    assert len(impacts) == 4

    expected_customers = {"cust_acme", "cust_birch", "cust_cedar", "cust_delta"}
    expected_commitments = {
        "com_acme_sso",
        "com_birch_audit",
        "com_cedar_export",
        "com_delta_sso",
    }

    actual_customers = {item["customer"]["id"] for item in impacts}
    actual_commitments = {item["commitment_id"] for item in impacts}

    assert actual_customers == expected_customers
    assert actual_commitments == expected_commitments

    # Verify structure of each impact
    for item in impacts:
        assert isinstance(item["title"], str) and item["title"]
        assert isinstance(item["due_at"], int)
        assert item["status"] in ("date_conflict", "needs_verification", "no_detected_conflict")
        assert isinstance(item["reasons"], list)
        assert isinstance(item["blockers"], list)

        # Paths and nodes/edges verification
        assert isinstance(item["paths"], list)
        assert len(item["paths"]) >= 1
        for path in item["paths"]:
            assert "nodes" in path and "edges" in path
            assert len(path["nodes"]) > 0
            for node in path["nodes"]:
                assert "id" in node
                assert "label" in node
                assert node["kind"] in ("customer", "commitment", "feature", "component", "project")
            for edge in path["edges"]:
                assert "from_id" in edge
                assert "to_id" in edge
                assert "relation" in edge
                assert "source_id" in edge

        # Citations
        assert isinstance(item["citations"], list)
        assert len(item["citations"]) >= 1
        for citation in item["citations"]:
            assert "source_id" in citation
            assert "quote" in citation

        # Engineering and account owners
        assert "engineering_owner" in item
        assert "account_owner" in item
        if item["engineering_owner"] is not None:
            assert "id" in item["engineering_owner"]
            assert "name" in item["engineering_owner"]
        if item["account_owner"] is not None:
            assert "id" in item["account_owner"]
            assert "name" in item["account_owner"]


def test_sources_endpoint():
    """Verify GET /api/sources/{source_id} returns source content and content_hash."""
    response = client.get("/api/sources/src_acme_handoff")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "src_acme_handoff"
    assert "body" in data
    assert "content_hash" in data
    assert len(data["content_hash"]) == 64  # SHA256 hex


def test_history_endpoint():
    """Verify GET /api/work-items/{id}/history returns forecast items with non-nullable decision_id."""
    response = client.get("/api/work-items/wi_permissions/history")
    assert response.status_code == 200
    data = response.json()
    assert "evidence_version" in data
    assert "forecasts" in data
    assert len(data["forecasts"]) >= 1
    forecast = data["forecasts"][0]
    assert forecast["decision_id"] == "DEC-12"
    assert "available_at" in forecast
    assert "valid_from" in forecast
    assert forecast["valid_to"] is None


def test_decisions_preview_and_confirm():
    """Verify decision preview assigns effective_at and confirm returns new evidence version."""
    preview_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to Oct 28. Owner: Priya."},
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert "preview_id" in preview_data
    assert "expires_at" in preview_data
    assert preview_data["proposal"]["work_item_id"] == "wi_permissions"
    assert isinstance(preview_data["proposal"]["effective_at"], int)

    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_data["preview_id"],
            "expected_version": preview_data["evidence_version"],
            "idempotency_key": "idem_test_001",
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert "decision_id" in confirm_data
    assert confirm_data["changed_work_item_ids"] == ["wi_permissions"]


def test_agent_run_endpoint():
    """Verify POST /api/agent/run returns cited answer, tool trace, and drafts."""
    response = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact on Acme SSO?",
            "commitment_id": "com_acme_sso",
            "expected_version": "ds_demo_001.rev_001",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert "answer" in data
    assert len(data["citations"]) > 0
    assert len(data["drafts"]) > 0
    assert len(data["tool_trace"]) > 0


def test_actions_endpoints():
    """Verify POST and GET /api/actions."""
    create_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "idem_act_001",
            "expected_version": "ds_demo_001.rev_001",
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Escalation draft message for reviewed action.",
            "citations": [
                {
                    "source_id": "src_permissions_ticket",
                    "quote": "delivery moves from October 21, 2026 to October 28, 2026",
                }
            ],
            "based_on_decision_ids": ["DEC-12"],
        },
    )
    assert create_res.status_code == 200
    create_data = create_res.json()
    assert "action_id" in create_data
    assert create_data["status"] == "reviewed"

    list_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert "actions" in list_data
    assert len(list_data["actions"]) > 0


def test_demo_reset_and_ingest():
    """Verify POST /api/demo/reset and POST /api/ingest."""
    reset_res = client.post("/api/demo/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "reset"

    ingest_res = client.post("/api/ingest", json={})
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] == "ingested"
