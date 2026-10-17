"""Phase 3 test suite verifying decision previews, confirms, agent runs, actions, and end-to-end workflows."""

import asyncio
import time
import pytest
from fastapi.testclient import TestClient

from backend.app.errors import (
    IdempotencyConflictError,
    PreviewExpiredError,
    ReviewRequiredError,
    StaleVersionError,
)
from backend.app.main import app
from backend.app.schemas import (
    ActionCreateRequest,
    DecisionConfirmRequest,
    DecisionPreviewRequest,
    DecisionProposal,
    SourceRef,
)
from backend.app.services.demo_service import (
    get_active_dataset_id,
    get_active_evidence_version,
    set_active_dataset,
)
from backend.app.services.preview_store import PreviewStore

client = TestClient(app)


# ---------------------------------------------------------------------------
# TASK-PVN-301: In-Memory Preview Store Tests
# ---------------------------------------------------------------------------

def test_preview_store_put_get_pop_and_expiry():
    """Verify PreviewStore handles storage, lookup, pop, and expiration eviction."""
    store = PreviewStore(ttl_seconds=1)  # 1 second TTL for test
    proposal = DecisionProposal(
        work_item_id="wi_permissions",
        available_at=1793212800000,
        effective_at=1792512000000,
        supersedes_id="fc_baseline",
        owner_id="person_priya",
        evidence_quote="Test quote",
    )

    now_ms = 1000000
    record = store.put("prev_test_1", proposal, "ds_1:rev_1", now_ms=now_ms)
    assert record.preview_id == "prev_test_1"
    assert record.expires_at == now_ms + 1000

    # Retrieve before expiration
    fetched = store.get("prev_test_1", now_ms=now_ms + 500)
    assert fetched.preview_id == "prev_test_1"

    # Expired lookup raises PreviewExpiredError
    with pytest.raises(PreviewExpiredError):
        store.get("prev_test_1", now_ms=now_ms + 1500)

    # Pop removes item
    store.put("prev_test_2", proposal, "ds_1:rev_1", now_ms=now_ms)
    popped = store.pop("prev_test_2", now_ms=now_ms)
    assert popped.preview_id == "prev_test_2"

    with pytest.raises(PreviewExpiredError):
        store.get("prev_test_2", now_ms=now_ms)


# ---------------------------------------------------------------------------
# TASK-PVN-302: Decision Preview Service & R1 Rules
# ---------------------------------------------------------------------------

def test_decision_preview_assigns_server_effective_at():
    """Verify decision preview sets effective_at = server preview creation time."""
    before_ms = int(time.time() * 1000)
    response = client.post(
        "/api/decisions/preview",
        json={
            "text": "Approved: permissions service delivery moves to October 28, 2026. Owner: Priya.",
            "source_title": "Permissions Delivery Memo",
        },
    )
    after_ms = int(time.time() * 1000)

    assert response.status_code == 200
    data = response.json()
    assert "preview_id" in data
    assert data["preview_id"].startswith("prev_")

    proposal = data["proposal"]
    assert proposal["work_item_id"] == "wi_permissions"
    assert proposal["owner_id"] == "person_priya"
    assert before_ms <= proposal["effective_at"] <= after_ms
    assert proposal["available_at"] == 1793212800000


def test_decision_preview_rejects_backdated_or_custom_effective_time():
    """R1 Rule 4: Reject explicit requests for custom historical or future decision-effective times with 422."""
    response = client.post(
        "/api/decisions/preview",
        json={
            "text": "Approved: permissions service moves to Oct 28. Backdate to 2026-09-01.",
            "source_title": "Backdated Note",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "review_required"
    assert "human review" in data["error"]["message"].lower()


def test_decision_preview_rejects_ownership_reassignment():
    """R1 Rule: Reassignment of component ownership requires human review (422 review_required)."""
    response = client.post(
        "/api/decisions/preview",
        json={
            "text": "Approved: permissions delivery moves to Oct 28. Reassign owner to Omar.",
            "source_title": "Reassignment Note",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "review_required"


# ---------------------------------------------------------------------------
# TASK-PVN-303: Decision Confirmation, Version Validation & Idempotency
# ---------------------------------------------------------------------------

def test_decision_confirmation_lifecycle_and_idempotency_replay():
    """Verify full preview -> confirm flow, single-use preview, and idempotency replay."""
    # 1. Reset demo to clean state
    reset_res = client.post("/api/demo/reset")
    initial_version = reset_res.json()["evidence_version"]

    # 2. Preview proposal
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    preview_id = prev_data["preview_id"]

    # 3. Confirm decision
    idempotency_key = "idem_test_wf_001"
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": initial_version,
            "idempotency_key": idempotency_key,
        },
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["decision_id"] == "DEC-13"
    assert confirm_data["changed_work_item_ids"] == ["wi_permissions"]
    new_version = confirm_data["evidence_version"]
    assert new_version != initial_version

    # 4. Idempotency Replay: identical request returns cached result
    replay_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": initial_version,
            "idempotency_key": idempotency_key,
        },
    )
    assert replay_res.status_code == 200
    assert replay_res.json() == confirm_data

    # 5. Idempotency Conflict: same key with different parameters returns 409 idempotency_conflict
    conflict_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": "different_preview_id",
            "expected_version": initial_version,
            "idempotency_key": idempotency_key,
        },
    )
    assert conflict_res.status_code == 409
    assert conflict_res.json()["error"]["code"] == "idempotency_conflict"

    # 6. Attempting to use popped preview with new key fails with 410 preview_expired
    expired_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": new_version,
            "idempotency_key": "new_unique_key_002",
        },
    )
    assert expired_res.status_code == 410
    assert expired_res.json()["error"]["code"] == "preview_expired"


def test_decision_confirm_rejects_stale_expected_version():
    """Verify confirm rejects outdated expected_version with 409 stale_evidence."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    preview_id = prev_res.json()["preview_id"]

    # Supply an invalid/old expected_version
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": "ds_stale_version:rev_999",
            "idempotency_key": "idem_stale_001",
        },
    )
    assert confirm_res.status_code == 409
    assert confirm_res.json()["error"]["code"] == "stale_evidence"


# ---------------------------------------------------------------------------
# TASK-PVN-304: Agent Run Service (2 Bounded Question Types)
# ---------------------------------------------------------------------------

def test_agent_run_impact_and_owners_query():
    """Question Type 1: Affected promises and owners."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    response = client.post(
        "/api/agent/run",
        json={
            "message": "Which commitments are impacted and who are the owners?",
            "commitment_id": "com_acme_sso",
            "expected_version": active_version,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert "Acme Corp" in data["answer"]
    assert "Priya Sharma" in data["answer"]
    assert len(data["citations"]) >= 1
    assert len(data["drafts"]) >= 1
    assert any(d["kind"] == "internal_escalation" for d in data["drafts"])
    assert any(t["tool"] == "find_impacted_commitments" for t in data["tool_trace"])


def test_agent_run_decision_lineage_query():
    """Question Type 2: Forecast and decision lineage."""
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
    assert any("DEC-12" in c["quote"] for c in data["citations"])
    assert any(t["tool"] == "get_forecast_history" for t in data["tool_trace"])


def test_agent_run_stale_version_rejected():
    """Verify agent run rejects mismatched expected_version with 409 stale_evidence."""
    response = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact?",
            "expected_version": "ds_wrong_version:rev_0",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_evidence"


# ---------------------------------------------------------------------------
# TASK-PVN-305: Action Persistence & Retrieval Service
# ---------------------------------------------------------------------------

def test_action_persistence_retrieval_and_idempotency():
    """Verify action creation, idempotency replay, and listing with original version preserved."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    action_key = "idem_act_test_001"

    payload = {
        "idempotency_key": action_key,
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
        "based_on_decision_ids": ["DEC-13"],
    }

    # 1. Create action
    create_res = client.post("/api/actions", json=payload)
    assert create_res.status_code == 200
    create_data = create_res.json()
    action_id = create_data["action_id"]
    assert create_data["status"] == "reviewed"
    assert create_data["evidence_version"] == active_version

    # 2. Idempotency Replay
    replay_res = client.post("/api/actions", json=payload)
    assert replay_res.status_code == 200
    assert replay_res.json()["action_id"] == action_id

    # 3. Idempotency Conflict
    conflict_payload = dict(payload)
    conflict_payload["body"] = "Completely different body text"
    conflict_res = client.post("/api/actions", json=conflict_payload)
    assert conflict_res.status_code == 409
    assert conflict_res.json()["error"]["code"] == "idempotency_conflict"

    # 4. List actions for commitment
    list_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["evidence_version"] == active_version
    matched = [a for a in list_data["actions"] if a["id"] == action_id]
    assert len(matched) == 1
    assert matched[0]["assignee_id"] == "person_priya"
    assert matched[0]["status"] == "reviewed"


def test_action_validation_rejects_empty_required_fields():
    """Verify action creation rejects empty assignee or citations with 422."""
    active_version = client.get("/api/impacts").json()["evidence_version"]
    res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "idem_empty_001",
            "expected_version": active_version,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "",  # Empty assignee
            "body": "Draft message",
            "citations": [],
            "based_on_decision_ids": ["DEC-12"],
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "review_required"


# ---------------------------------------------------------------------------
# TASK-PVN-306: Complete End-to-End Workflow Verification
# ---------------------------------------------------------------------------

def test_complete_end_to_end_hackathon_story_workflow():
    """Complete end-to-end hackathon story simulation:

    1. Reset demo graph to baseline -> get fresh dataset_id:rev_1.
    2. Query baseline impacts -> verify 4 commitments, 0 date conflicts.
    3. Preview decision ticket moving permissions delivery to Oct 28.
    4. Confirm decision under mutation lock -> bump to rev_2.
    5. Query updated impacts -> Acme & Birch enter date_conflict with Priya as owner.
    6. Run agent for Acme SSO -> receive cited analysis & escalation draft.
    7. Save reviewed action -> verify stored with status='reviewed'.
    8. List actions -> verify action appears in commitment log.
    """
    # Step 1: Reset demo
    reset_res = client.post("/api/demo/reset")
    assert reset_res.status_code == 200
    v1 = reset_res.json()["evidence_version"]
    assert v1.endswith(":rev_1")

    # Step 2: Baseline impacts
    impacts_res1 = client.get("/api/impacts")
    assert impacts_res1.status_code == 200
    impacts1 = impacts_res1.json()["impacts"]
    assert len(impacts1) == 4
    for imp in impacts1:
        assert imp["status"] == "no_detected_conflict"

    # Step 3: Decision preview
    preview_res = client.post(
        "/api/decisions/preview",
        json={
            "text": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12.",
            "source_title": "Permissions Delivery Memo",
        },
    )
    assert preview_res.status_code == 200
    preview_id = preview_res.json()["preview_id"]

    # Step 4: Decision confirmation
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": v1,
            "idempotency_key": "e2e_confirm_idem_001",
        },
    )
    assert confirm_res.status_code == 200
    v2 = confirm_res.json()["evidence_version"]
    assert v2.endswith(":rev_2")

    # Step 5: Updated impacts reflecting R1 owner resolution
    impacts_res2 = client.get("/api/impacts")
    assert impacts_res2.status_code == 200
    impacts2 = impacts_res2.json()["impacts"]

    by_id = {imp["commitment_id"]: imp for imp in impacts2}
    assert by_id["com_acme_sso"]["status"] == "date_conflict"
    assert by_id["com_birch_audit"]["status"] == "date_conflict"
    assert by_id["com_cedar_export"]["status"] == "no_detected_conflict"
    assert by_id["com_delta_sso"]["status"] == "no_detected_conflict"

    # Blocking component owner (Priya Sharma) is the resolved engineering owner for date conflicts
    assert by_id["com_acme_sso"]["engineering_owner"]["name"] == "Priya Sharma"
    assert by_id["com_birch_audit"]["engineering_owner"]["name"] == "Priya Sharma"

    # Step 6: Agent reasoning run
    agent_res = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact on Acme Corp and who should be contacted?",
            "commitment_id": "com_acme_sso",
            "expected_version": v2,
        },
    )
    assert agent_res.status_code == 200
    agent_data = agent_res.json()
    assert agent_data["status"] == "complete"
    assert len(agent_data["drafts"]) >= 1

    # Step 7: Persist reviewed escalation action
    draft = agent_data["drafts"][0]
    action_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "e2e_action_idem_001",
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
    action_id = action_res.json()["action_id"]

    # Step 8: Verify action list contains the saved action
    list_res = client.get("/api/actions?commitment_id=com_acme_sso")
    assert list_res.status_code == 200
    actions = list_res.json()["actions"]
    assert any(a["id"] == action_id for a in actions)
