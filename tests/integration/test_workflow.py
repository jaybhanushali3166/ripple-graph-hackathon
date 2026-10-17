"""End-to-end integration tests simulating the complete 8-step hackathon storyline.

TASK-PVN-402:
1. Reset demo graph (POST /api/demo/reset) -> fresh dataset identity & rev_1.
2. Query baseline impacts (GET /api/impacts) -> verify 4 commitments, 0 date conflicts.
3. Inspect baseline source (GET /api/sources/src_permissions_ticket) & history (GET /api/work-items/wi_permissions/history) verifying non-nullable DEC-12.
4. Preview decision note (POST /api/decisions/preview) with server-assigned effective_at and 15-min TTL.
5. Confirm decision atomically (POST /api/decisions/confirm) with expected_version -> bumps to rev_2.
6. Query updated impacts (GET /api/impacts) -> verify Acme & Birch enter date_conflict with Priya Sharma as blocking engineering owner; Cedar & Delta remain controls.
7. Run agent query (POST /api/agent/run) for Acme impact and DEC-12 lineage -> verify cited answer and drafts.
8. Persist reviewed action (POST /api/actions) -> status='reviewed' and verify in GET /api/actions.
"""

import time
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_complete_hackathon_8_step_storyline():
    """Execute the canonical 8-step hackathon storyline seamlessly end-to-end."""

    # -------------------------------------------------------------------------
    # Step 1: Reset demo graph -> fresh dataset identity & rev_1
    # -------------------------------------------------------------------------
    reset_res = client.post("/api/demo/reset")
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["status"] == "reset"
    dataset_id = reset_data["dataset_id"]
    assert dataset_id.startswith("ds_")
    v1 = reset_data["evidence_version"]
    assert v1 == f"{dataset_id}:rev_1"

    # -------------------------------------------------------------------------
    # Step 2: Query baseline impacts -> 4 commitments, 0 date conflicts
    # -------------------------------------------------------------------------
    impacts_res_1 = client.get("/api/impacts")
    assert impacts_res_1.status_code == 200
    assert impacts_res_1.headers.get("x-mock-mode") == "true"
    impacts_data_1 = impacts_res_1.json()
    assert impacts_data_1["evidence_version"] == v1
    assert impacts_data_1["completeness"]["complete"] is True
    assert impacts_data_1["completeness"]["warnings"] == []

    impacts_1 = impacts_data_1["impacts"]
    assert len(impacts_1) == 4
    expected_commitments = {
        "com_acme_sso",
        "com_birch_audit",
        "com_cedar_export",
        "com_delta_sso",
    }
    assert {imp["commitment_id"] for imp in impacts_1} == expected_commitments

    for imp in impacts_1:
        assert imp["status"] == "no_detected_conflict"
        assert len(imp["blockers"]) == 0
        assert len(imp["paths"]) >= 1
        assert len(imp["citations"]) >= 1

    # -------------------------------------------------------------------------
    # Step 3: Inspect baseline source & work item history verifying non-nullable DEC-12
    # -------------------------------------------------------------------------
    source_res = client.get("/api/sources/src_permissions_ticket")
    assert source_res.status_code == 200
    source_data = source_res.json()
    assert source_data["id"] == "src_permissions_ticket"
    assert "Permissions service" in source_data["body"]
    assert "DEC-12" in source_data["body"]
    assert len(source_data["content_hash"]) == 64

    history_res = client.get("/api/work-items/wi_permissions/history")
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["evidence_version"] == v1
    assert len(history_data["forecasts"]) >= 1
    baseline_forecast = history_data["forecasts"][0]
    assert baseline_forecast["decision_id"] == "DEC-12"
    assert baseline_forecast["decision_id"] is not None
    assert baseline_forecast["valid_from"] is not None
    assert baseline_forecast["valid_to"] is None

    # -------------------------------------------------------------------------
    # Step 4: Preview decision note with server-assigned effective_at and 15-min TTL
    # -------------------------------------------------------------------------
    before_preview_ms = int(time.time() * 1000)
    decision_text = (
        "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
        "Owner: Priya. This replaces decision DEC-12."
    )
    preview_res = client.post(
        "/api/decisions/preview",
        json={
            "text": decision_text,
            "source_title": "Permissions Delivery Memo",
        },
    )
    after_preview_ms = int(time.time() * 1000)
    assert preview_res.status_code == 200
    preview_data = preview_res.json()

    preview_id = preview_data["preview_id"]
    assert preview_id.startswith("prev_")
    assert preview_data["evidence_version"] == v1

    proposal = preview_data["proposal"]
    assert proposal["work_item_id"] == "wi_permissions"
    assert proposal["owner_id"] == "person_priya"
    assert proposal["available_at"] == 1793212800000
    # Server assigns effective_at = preview created time
    assert before_preview_ms <= proposal["effective_at"] <= after_preview_ms
    # 15-minute TTL
    expected_expiry = proposal["effective_at"] + (15 * 60 * 1000)
    assert abs(preview_data["expires_at"] - expected_expiry) < 2000

    # -------------------------------------------------------------------------
    # Step 5: Confirm decision atomically with expected_version -> bumps to rev_2
    # -------------------------------------------------------------------------
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": v1,
            "idempotency_key": "storyline_confirm_step_5",
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["decision_id"] == "DEC-13"
    assert confirm_data["changed_work_item_ids"] == ["wi_permissions"]
    v2 = confirm_data["evidence_version"]
    assert v2 == f"{dataset_id}:rev_2"

    # -------------------------------------------------------------------------
    # Step 6: Query updated impacts -> Acme & Birch enter date_conflict with Priya
    #         as blocking owner; Cedar & Delta remain controls
    # -------------------------------------------------------------------------
    impacts_res_2 = client.get("/api/impacts")
    assert impacts_res_2.status_code == 200
    impacts_data_2 = impacts_res_2.json()
    assert impacts_data_2["evidence_version"] == v2

    by_id = {imp["commitment_id"]: imp for imp in impacts_data_2["impacts"]}

    # Acme and Birch date conflicts
    assert by_id["com_acme_sso"]["status"] == "date_conflict"
    assert by_id["com_birch_audit"]["status"] == "date_conflict"

    # Priya Sharma is the blocking engineering owner
    assert by_id["com_acme_sso"]["engineering_owner"]["id"] == "person_priya"
    assert by_id["com_acme_sso"]["engineering_owner"]["name"] == "Priya Sharma"
    assert by_id["com_birch_audit"]["engineering_owner"]["id"] == "person_priya"
    assert by_id["com_birch_audit"]["engineering_owner"]["name"] == "Priya Sharma"

    # Cedar and Delta remain controls (no conflicts)
    assert by_id["com_cedar_export"]["status"] == "no_detected_conflict"
    assert by_id["com_delta_sso"]["status"] == "no_detected_conflict"
    assert len(by_id["com_cedar_export"]["blockers"]) == 0
    assert len(by_id["com_delta_sso"]["blockers"]) == 0

    # -------------------------------------------------------------------------
    # Step 7: Run agent query for Acme impact and DEC-12 lineage
    # -------------------------------------------------------------------------
    # 7a. Acme impact and owner query
    agent_impact_res = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact on Acme SSO and who is the owner?",
            "commitment_id": "com_acme_sso",
            "expected_version": v2,
        },
    )
    assert agent_impact_res.status_code == 200
    agent_impact_data = agent_impact_res.json()
    assert agent_impact_data["status"] == "complete"
    assert "Acme" in agent_impact_data["answer"]
    assert "Priya Sharma" in agent_impact_data["answer"]
    assert len(agent_impact_data["citations"]) >= 1
    assert len(agent_impact_data["drafts"]) >= 1
    assert len(agent_impact_data["tool_trace"]) >= 1

    # 7b. DEC-12 lineage query
    agent_lineage_res = client.post(
        "/api/agent/run",
        json={
            "message": "Why did the permissions forecast change from DEC-12?",
            "commitment_id": "com_acme_sso",
            "expected_version": v2,
        },
    )
    assert agent_lineage_res.status_code == 200
    agent_lineage_data = agent_lineage_res.json()
    assert agent_lineage_data["status"] == "complete"
    assert "DEC-12" in agent_lineage_data["answer"]
    assert any("DEC-12" in c["quote"] for c in agent_lineage_data["citations"])

    # -------------------------------------------------------------------------
    # Step 8: Persist reviewed action -> status='reviewed' and verify in GET /api/actions
    # -------------------------------------------------------------------------
    draft = agent_impact_data["drafts"][0]
    action_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "storyline_action_step_8",
            "expected_version": v2,
            "commitment_id": draft["commitment_id"],
            "kind": draft["kind"],
            "assignee_id": draft["assignee_id"] or "person_priya",
            "body": draft["body"],
            "citations": draft["citations"],
            "based_on_decision_ids": draft["based_on_decision_ids"],
        },
    )
    assert action_res.status_code == 200
    action_data = action_res.json()
    assert "action_id" in action_data
    assert action_data["action_id"].startswith("act_")
    assert action_data["status"] == "reviewed"
    assert action_data["evidence_version"] == v2
    created_action_id = action_data["action_id"]

    # Verify action appears in GET /api/actions
    list_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["evidence_version"] == v2
    saved_actions = list_data["actions"]
    assert any(
        a["id"] == created_action_id and a["status"] == "reviewed"
        for a in saved_actions
    )
