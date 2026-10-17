"""Dedicated unit tests for /api/actions endpoints.

Tests cover:
- Action creation (POST /api/actions) with reviewed status and evidence version
- Field-level validation: empty assignee, body, citations, or decision IDs (422 review_required)
- Missing required fields schema rejection (422 invalid_input)
- Stale evidence version rejection (409 stale_evidence)
- Idempotency replay with identical payload
- Idempotency conflict with mismatched payload (409 idempotency_conflict)
- Citation quote verification and source logging
- Listing actions (GET /api/actions) and filtering by commitment_id
- Version provenance preservation across knowledge revisions
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_to_clean_state():
    """Reset demo state before each test to ensure isolated dataset and revision."""
    client.post("/api/demo/reset")


def test_action_create_success():
    """Verify POST /api/actions creates an action with status='reviewed' and returns action_id."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    payload = {
        "idempotency_key": "act_unit_key_001",
        "expected_version": active_version,
        "commitment_id": "com_acme_sso",
        "kind": "internal_escalation",
        "assignee_id": "person_priya",
        "body": "Priya: Acme SSO is promised for Oct 23. Please advise on staging rollout.",
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "delivery moves from October 21, 2026 to October 28, 2026",
            }
        ],
        "based_on_decision_ids": ["DEC-12", "DEC-13"],
    }

    response = client.post("/api/actions", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "action_id" in data
    assert data["action_id"].startswith("act_")
    assert data["status"] == "reviewed"
    assert data["evidence_version"] == active_version
    assert isinstance(data["created_at"], int)


@pytest.mark.parametrize(
    "invalid_field,invalid_value",
    [
        ("assignee_id", ""),
        ("assignee_id", "   "),
        ("body", ""),
        ("body", "   "),
        ("citations", []),
        ("based_on_decision_ids", []),
    ],
)
def test_action_create_validates_required_fields(invalid_field, invalid_value):
    """Empty assignee, body, citations, or based_on_decision_ids return 422 review_required."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    payload = {
        "idempotency_key": f"act_invalid_{invalid_field}",
        "expected_version": active_version,
        "commitment_id": "com_acme_sso",
        "kind": "internal_escalation",
        "assignee_id": "person_priya",
        "body": "Valid body text",
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "delivery moves from October 21, 2026 to October 28, 2026",
            }
        ],
        "based_on_decision_ids": ["DEC-12"],
    }
    payload[invalid_field] = invalid_value

    response = client.post("/api/actions", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "review_required"


def test_action_create_schema_validation_missing_fields():
    """Missing required schema fields return 422 invalid_input."""
    response = client.post("/api/actions", json={"idempotency_key": "k"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_action_create_stale_evidence_version():
    """Verify action creation with outdated expected_version returns 409 stale_evidence."""
    payload = {
        "idempotency_key": "act_stale_001",
        "expected_version": "ds_stale_id:rev_999",
        "commitment_id": "com_acme_sso",
        "kind": "internal_escalation",
        "assignee_id": "person_priya",
        "body": "Valid body text",
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "delivery moves from October 21, 2026 to October 28, 2026",
            }
        ],
        "based_on_decision_ids": ["DEC-12"],
    }
    response = client.post("/api/actions", json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_evidence"


def test_action_create_idempotency_replay_and_conflict():
    """Verify identical request replays cached action, while mismatched payload triggers 409 conflict."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    key = "idem_act_test_replay_001"
    payload = {
        "idempotency_key": key,
        "expected_version": active_version,
        "commitment_id": "com_acme_sso",
        "kind": "internal_escalation",
        "assignee_id": "person_priya",
        "body": "Original message body",
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "delivery moves from October 21, 2026 to October 28, 2026",
            }
        ],
        "based_on_decision_ids": ["DEC-12"],
    }

    # 1. Create action
    res1 = client.post("/api/actions", json=payload)
    assert res1.status_code == 200
    res1_data = res1.json()

    # 2. Replay with identical payload returns cached result
    res2 = client.post("/api/actions", json=payload)
    assert res2.status_code == 200
    assert res2.json() == res1_data

    # 3. Conflict: same key with altered body returns 409 idempotency_conflict
    conflict_payload = dict(payload)
    conflict_payload["body"] = "Altered body text causing conflict"
    res3 = client.post("/api/actions", json=conflict_payload)
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "idempotency_conflict"


def test_action_citation_verification():
    """Verify action creation succeeds with valid citation and source."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    payload = {
        "idempotency_key": "act_citation_test_001",
        "expected_version": active_version,
        "commitment_id": "com_acme_sso",
        "kind": "customer_update",
        "assignee_id": "person_maya",
        "body": "Customer update for Acme Corp regarding timeline adjustments.",
        "citations": [
            {
                "source_id": "src_permissions_ticket",
                "quote": "delivery moves from October 21, 2026 to October 28, 2026",
            }
        ],
        "based_on_decision_ids": ["DEC-12"],
    }
    response = client.post("/api/actions", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"


def test_action_listing_and_filtering_by_commitment():
    """Verify GET /api/actions returns saved actions, and filters by commitment_id."""
    active_version = client.get("/api/impacts").json()["evidence_version"]

    # Create action for Acme
    client.post(
        "/api/actions",
        json={
            "idempotency_key": "list_act_acme_001",
            "expected_version": active_version,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Acme escalation message",
            "citations": [{"source_id": "src_permissions_ticket", "quote": "delivery moves"}],
            "based_on_decision_ids": ["DEC-12"],
        },
    )

    # Create action for Birch
    client.post(
        "/api/actions",
        json={
            "idempotency_key": "list_act_birch_001",
            "expected_version": active_version,
            "commitment_id": "com_birch_audit",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Birch escalation message",
            "citations": [{"source_id": "src_permissions_ticket", "quote": "delivery moves"}],
            "based_on_decision_ids": ["DEC-12"],
        },
    )

    # 1. List all actions
    all_res = client.get("/api/actions")
    assert all_res.status_code == 200
    all_actions = all_res.json()["actions"]
    all_commitment_ids = {a["commitment_id"] for a in all_actions}
    assert "com_acme_sso" in all_commitment_ids
    assert "com_birch_audit" in all_commitment_ids

    # 2. Filter by com_acme_sso
    acme_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert acme_res.status_code == 200
    acme_actions = acme_res.json()["actions"]
    assert len(acme_actions) >= 1
    assert all(a["commitment_id"] == "com_acme_sso" for a in acme_actions)

    # 3. Filter by com_birch_audit
    birch_res = client.get("/api/actions?commitment_id=com_birch_audit")
    assert birch_res.status_code == 200
    birch_actions = birch_res.json()["actions"]
    assert len(birch_actions) >= 1
    assert all(a["commitment_id"] == "com_birch_audit" for a in birch_actions)

    # 4. Filter by non-existent commitment returns empty list
    none_res = client.get("/api/actions?commitment_id=com_nonexistent_xyz")
    assert none_res.status_code == 200
    assert none_res.json()["actions"] == []


def test_action_version_provenance_preserved():
    """Verify that an action created at rev_1 maintains its original evidence_version when rev_2 is created."""
    v1 = client.get("/api/impacts").json()["evidence_version"]
    assert v1.endswith(":rev_1")

    # Create action at rev_1
    create_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "provenance_act_001",
            "expected_version": v1,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Provenance action message",
            "citations": [{"source_id": "src_permissions_ticket", "quote": "delivery moves"}],
            "based_on_decision_ids": ["DEC-12"],
        },
    )
    assert create_res.status_code == 200
    action_id = create_res.json()["action_id"]

    # Bump knowledge revision to rev_2 via decision confirm
    p_data = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya."},
    ).json()
    c_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": p_data["preview_id"],
            "expected_version": v1,
            "idempotency_key": "bump_key_for_action_test",
        },
    )
    v2 = c_res.json()["evidence_version"]
    assert v2.endswith(":rev_2")

    # Retrieve actions and check provenance of the rev_1 action
    list_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    items = list_res.json()["actions"]
    matched = [a for a in items if a["id"] == action_id]
    assert len(matched) == 1
    # Original action preserves v1
    assert matched[0]["evidence_version"] == v1
