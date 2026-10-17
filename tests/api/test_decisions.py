"""Dedicated unit tests for /api/decisions/preview and /api/decisions/confirm endpoints.

Tests cover:
- Proposal extraction and server-assigned effective_at timestamp
- 15-minute TTL assignment (expires_at)
- Quote matching and verification against input text
- Rejection of custom/backdated effective_at with 422 review_required
- Rejection of ownership reassignment with 422 review_required
- Rejection of ambiguous text with 422 review_required
- Request validation envelopes (422 invalid_input)
- Atomic confirmation and revision bumping
- Single-use preview popping and 410 preview_expired handling
- Outdated expected_version rejection with 409 stale_evidence
- Idempotency replay with identical payload
- Idempotency conflict with mismatched payload (409 idempotency_conflict)
- PreviewStore direct operations (put, get, pop, clear, TTL expiry)
"""

import time
import pytest
from fastapi.testclient import TestClient

from backend.app.errors import PreviewExpiredError
from backend.app.main import app
from backend.app.schemas import DecisionProposal
from backend.app.services.preview_store import PreviewStore, get_preview_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_to_clean_state():
    """Reset demo state before each test to ensure isolated dataset and revision."""
    client.post("/api/demo/reset")


def test_decision_preview_success_and_server_effective_at():
    """Verify decision preview assigns server effective_at timestamp and 15-min TTL."""
    before_ms = int(time.time() * 1000)
    response = client.post(
        "/api/decisions/preview",
        json={
            "text": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya.",
            "source_title": "Permissions Delivery Memo",
        },
    )
    after_ms = int(time.time() * 1000)

    assert response.status_code == 200
    data = response.json()

    assert "preview_id" in data
    assert data["preview_id"].startswith("prev_")
    assert "evidence_version" in data
    assert data["evidence_version"].endswith(":rev_1")

    # 15-minute TTL: expires_at is roughly created_at + 900,000 ms
    proposal = data["proposal"]
    created_at = proposal["effective_at"]
    assert before_ms <= created_at <= after_ms
    expected_expires = created_at + 900_000
    assert abs(data["expires_at"] - expected_expires) < 2000

    # Proposal content validation
    assert proposal["work_item_id"] == "wi_permissions"
    assert proposal["owner_id"] == "person_priya"
    assert proposal["available_at"] in (1793212199999, 1793212800000)
    assert proposal["supersedes_id"] in ("DEC-12", "fc_permissions_baseline")
    assert isinstance(proposal["evidence_quote"], str)
    assert len(proposal["evidence_quote"]) > 0


def test_decision_preview_quote_matching():
    """Verify that the proposal's evidence_quote is a valid substring of input text."""
    input_text = "Approved: permissions service moves to October 28, 2026. Owner: Priya."
    response = client.post(
        "/api/decisions/preview",
        json={"text": input_text},
    )
    assert response.status_code == 200
    quote = response.json()["proposal"]["evidence_quote"]
    assert quote in input_text


@pytest.mark.parametrize(
    "text",
    [
        "Approved: permissions service moves to Oct 28. Backdate to 2026-09-01.",
        "Approved: permissions service moves to Oct 28. Effective as of 2026-09-01.",
        "Approved: permissions service moves to Oct 28. Retroactively effective.",
        "Approved: permissions service moves to Oct 28. Effective from yesterday.",
    ],
)
def test_decision_preview_rejects_custom_or_backdated_effective_time(text):
    """R1 Rule 4: Reject requests for custom historical/future decision effective times with 422 review_required."""
    response = client.post(
        "/api/decisions/preview",
        json={"text": text},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "review_required"
    assert "human review" in data["error"]["message"].lower()


@pytest.mark.parametrize(
    "text",
    [
        "Approved: permissions delivery moves to Oct 28. Reassign owner to Omar.",
        "Approved: permissions delivery moves to Oct 28. Transfer ownership to Alex.",
        "Approved: permissions delivery moves to Oct 28. Change owner to Sam.",
    ],
)
def test_decision_preview_rejects_ownership_reassignment(text):
    """R1 Rule: Reassignment of component ownership requires human review (422 review_required)."""
    response = client.post(
        "/api/decisions/preview",
        json={"text": text},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "review_required"


def test_decision_preview_rejects_ambiguous_text():
    """Unparseable or ambiguous input returns 422 review_required."""
    response = client.post(
        "/api/decisions/preview",
        json={"text": "General team sync discussing Friday catering and travel expenses."},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "review_required"


def test_decision_preview_validation_errors():
    """Missing or empty required fields return 422 invalid_input."""
    res1 = client.post("/api/decisions/preview", json={})
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "invalid_input"

    res2 = client.post("/api/decisions/preview", json={"text": ""})
    assert res2.status_code == 422
    # Empty string text has no extractable work item
    assert res2.json()["error"]["code"] in ("invalid_input", "review_required")


def test_decision_confirm_success_and_version_bump():
    """Verify confirming a decision creates DEC-13 and bumps revision from rev_1 to rev_2."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    assert prev_res.status_code == 200
    p_data = prev_res.json()
    v1 = p_data["evidence_version"]

    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": p_data["preview_id"],
            "expected_version": v1,
            "idempotency_key": "confirm_unit_test_key_001",
        },
    )
    assert confirm_res.status_code == 200
    c_data = confirm_res.json()

    assert c_data["decision_id"] == "DEC-13"
    assert c_data["changed_work_item_ids"] == ["wi_permissions"]
    assert c_data["evidence_version"].endswith(":rev_2")
    assert c_data["evidence_version"] != v1


def test_decision_confirm_single_use_preview():
    """Verify proposal is popped on confirmation; second confirmation attempt with different key returns 410."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    p_data = prev_res.json()
    preview_id = p_data["preview_id"]
    v1 = p_data["evidence_version"]

    # First confirm succeeds
    res1 = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": v1,
            "idempotency_key": "single_use_key_1",
        },
    )
    assert res1.status_code == 200

    # Second confirm with different key fails with 410 preview_expired
    res2 = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": res1.json()["evidence_version"],
            "idempotency_key": "single_use_key_2",
        },
    )
    assert res2.status_code == 410
    assert res2.json()["error"]["code"] == "preview_expired"


def test_decision_confirm_stale_expected_version():
    """Verify confirm rejects an outdated expected_version with 409 stale_evidence."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    preview_id = prev_res.json()["preview_id"]

    res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": "ds_stale_12345:rev_0",
            "idempotency_key": "stale_key_001",
        },
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "stale_evidence"


def test_decision_confirm_idempotency_replay_and_conflict():
    """Verify exact replay returns cached response, while mismatched payload returns 409 idempotency_conflict."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    p_data = prev_res.json()
    preview_id = p_data["preview_id"]
    v1 = p_data["evidence_version"]
    key = "idem_decision_test_001"

    payload = {
        "preview_id": preview_id,
        "expected_version": v1,
        "idempotency_key": key,
    }

    # 1. Initial confirmation
    res1 = client.post("/api/decisions/confirm", json=payload)
    assert res1.status_code == 200
    res1_data = res1.json()

    # 2. Idempotent replay: identical payload returns same 200 response
    res2 = client.post("/api/decisions/confirm", json=payload)
    assert res2.status_code == 200
    assert res2.json() == res1_data

    # 3. Idempotency conflict: same key with mismatched preview_id returns 409
    conflict_payload = {
        "preview_id": "prev_different_id_123",
        "expected_version": v1,
        "idempotency_key": key,
    }
    res3 = client.post("/api/decisions/confirm", json=conflict_payload)
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "idempotency_conflict"


def test_preview_store_unit_operations():
    """Unit test PreviewStore lifecycle: put, get, pop, clear, and TTL expiration."""
    store = PreviewStore(ttl_seconds=10)
    proposal = DecisionProposal(
        work_item_id="wi_permissions",
        available_at=1793212800000,
        effective_at=1792512000000,
        supersedes_id="fc_baseline",
        owner_id="person_priya",
        evidence_quote="Test quote",
    )

    now_ms = 500000
    # Put
    rec = store.put("prev_unit_1", proposal, "ds_1:rev_1", now_ms=now_ms)
    assert rec.preview_id == "prev_unit_1"
    assert rec.expires_at == now_ms + 10_000

    # Get valid
    rec_fetched = store.get("prev_unit_1", now_ms=now_ms + 1000)
    assert rec_fetched.preview_id == "prev_unit_1"

    # Get expired raises PreviewExpiredError
    with pytest.raises(PreviewExpiredError):
        store.get("prev_unit_1", now_ms=now_ms + 11_000)

    # Pop removes item
    store.put("prev_unit_2", proposal, "ds_1:rev_1", now_ms=now_ms)
    popped = store.pop("prev_unit_2", now_ms=now_ms)
    assert popped.preview_id == "prev_unit_2"

    with pytest.raises(PreviewExpiredError):
        store.pop("prev_unit_2", now_ms=now_ms)

    # Clear empties store
    store.put("prev_unit_3", proposal, "ds_1:rev_1", now_ms=now_ms)
    store.clear()
    with pytest.raises(PreviewExpiredError):
        store.get("prev_unit_3", now_ms=now_ms)
