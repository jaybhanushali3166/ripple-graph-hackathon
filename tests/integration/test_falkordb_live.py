"""Live FalkorDB integration test.

Runs against a live FalkorDB instance when available.
Automatically skipped if FalkorDB is not reachable.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings import get_settings
from tests.conftest import is_falkordb_reachable

pytestmark = pytest.mark.skipif(
    not is_falkordb_reachable(),
    reason="Live FalkorDB instance is not reachable",
)


@pytest.fixture
def live_client(monkeypatch):
    """Test client configured to talk to live FalkorDB without mocks."""
    monkeypatch.setenv("DEV_MOCKS", "false")
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_live_falkordb_full_lifecycle(live_client):
    """End-to-end lifecycle test directly on live FalkorDB."""
    # 1. Reset demo graph
    reset_res = live_client.post("/api/demo/reset")
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["status"] in ("ok", "reset")
    v1 = reset_data["evidence_version"]
    assert ":" in v1

    # 2. Query baseline impacts
    impacts_res = live_client.get("/api/impacts")
    assert impacts_res.status_code == 200
    impacts_data = impacts_res.json()
    assert impacts_data["evidence_version"] == v1
    assert len(impacts_data["impacts"]) == 4
    for imp in impacts_data["impacts"]:
        assert imp["status"] == "no_detected_conflict"

    # 3. Inspect source and history
    src_res = live_client.get("/api/sources/src_permissions_ticket")
    assert src_res.status_code == 200
    src_data = src_res.json()
    assert src_data["id"] == "src_permissions_ticket"

    hist_res = live_client.get("/api/work-items/wi_permissions/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["evidence_version"] == v1
    assert len(hist_data["forecasts"]) >= 1

    # 4. Preview decision note
    note = (
        "Priya (2026-10-17 14:20 IST) in #eng-permissions: Load tests found a locking bug "
        "in the permissions service, so the old date will not hold.\n"
        "Approved: permissions service delivery moves to October 28, 2026.\n"
        "Owner: Priya."
    )
    preview_res = live_client.post(
        "/api/decisions/preview",
        json={
            "text": note,
            "source_title": "Slack #eng-permissions 2026-10-17",
        },
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    preview_id = preview_data["preview_id"]
    proposal = preview_data["proposal"]
    assert proposal["work_item_id"] == "wi_permissions"
    assert proposal["available_at"] in (1793212199999, 1793212800000)

    # 5. Confirm decision atomically
    confirm_res = live_client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": v1,
            "idempotency_key": "live_falkordb_test_confirm_1",
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    v2 = confirm_data["evidence_version"]
    assert v2 != v1 and ":" in v2

    # 6. Verify updated impacts
    updated_res = live_client.get("/api/impacts")
    assert updated_res.status_code == 200
    updated_data = updated_res.json()
    assert updated_data["evidence_version"] == v2
    by_id = {imp["commitment_id"]: imp for imp in updated_data["impacts"]}
    assert by_id["com_acme_sso"]["status"] == "date_conflict"
    assert by_id["com_birch_audit"]["status"] == "date_conflict"
    assert by_id["com_cedar_export"]["status"] == "no_detected_conflict"
    assert by_id["com_delta_sso"]["status"] == "no_detected_conflict"

    # 7. Persist reviewed action
    action_res = live_client.post(
        "/api/actions",
        json={
            "idempotency_key": "live_falkordb_action_1",
            "expected_version": v2,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Escalating date conflict for Acme SSO due to permissions delay.",
            "citations": [
                {
                    "source_id": "src_permissions_ticket",
                    "quote": "Forecast: permissions service available October 21, 2026 (see DEC-12).",
                }
            ],
            "based_on_decision_ids": [confirm_data["decision_id"]],
        },
    )
    assert action_res.status_code == 200
    action_data = action_res.json()
    assert action_data["status"] == "reviewed"

    # 8. List actions
    list_res = live_client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert len(list_data["actions"]) >= 1
    assert list_data["actions"][0]["id"] == action_data["action_id"]
