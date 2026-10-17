"""Integration tests for edge cases, concurrency, TTL expiry, and R1 contract compliance.

TASK-PVN-403:
- High concurrency under mutation_lock: simulate concurrent confirm requests with asyncio.gather / concurrent tasks.
- Stale evidence version rejection: sending outdated expected_version returns 409 stale_evidence.
- Proposal TTL expiry: lookup or confirm after expiry returns 410 preview_expired.
- Idempotency conflict: same idempotency_key with mismatched payload returns 409 idempotency_conflict.
- Idempotency replay: same idempotency_key with identical payload returns cached result.
- R1 Status Precedence: commitment with missing owner without date conflict becomes needs_verification;
  date_conflict with missing owner stays date_conflict with warning.
- Rejection of custom backdated effective_at with 422 review_required.
- Rejection of ownership reassignment with 422 review_required.
- Restart/reset persistence double: verify state reset behavior.
"""

import asyncio
import time
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas import Blocker, EntityOwner, Impact
from backend.app.services.demo_service import get_active_evidence_version
from tests.api.test_services import apply_r1_owner_resolution
from backend.app.services.preview_store import get_preview_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_to_clean_state():
    """Reset demo state before each test to guarantee an isolated dataset and revision."""
    client.post("/api/demo/reset")


# ---------------------------------------------------------------------------
# 1. High Concurrency Under Mutation Lock
# ---------------------------------------------------------------------------

def test_concurrent_confirms_serialized_under_mutation_lock():
    """Simulate concurrent confirmations: one succeeds and bumps to rev_2,

    while the competing concurrent request with the old rev_1 version is rejected with 409 stale_evidence.
    """
    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # 1. Reset demo to fresh state
            reset_res = await ac.post("/api/demo/reset")
            v1 = reset_res.json()["evidence_version"]

            # 2. Create two separate previews targeting the current revision
            prev1_res = await ac.post(
                "/api/decisions/preview",
                json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
            )
            prev2_res = await ac.post(
                "/api/decisions/preview",
                json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
            )
            p1 = prev1_res.json()["preview_id"]
            p2 = prev2_res.json()["preview_id"]

            # 3. Fire concurrent confirm requests targeting the same baseline revision
            res1, res2 = await asyncio.gather(
                ac.post(
                    "/api/decisions/confirm",
                    json={"preview_id": p1, "expected_version": v1, "idempotency_key": "conc_key_1"},
                ),
                ac.post(
                    "/api/decisions/confirm",
                    json={"preview_id": p2, "expected_version": v1, "idempotency_key": "conc_key_2"},
                ),
            )

            status_codes = sorted([res1.status_code, res2.status_code])
            # Exactly one must succeed (200) and one must be rejected with 409 stale_evidence
            assert status_codes == [200, 409]

            success_res = res1 if res1.status_code == 200 else res2
            rejected_res = res2 if res1.status_code == 200 else res1

            assert success_res.json()["decision_id"] == "DEC-13"
            assert success_res.json()["evidence_version"].endswith(":rev_2")

            assert rejected_res.json()["error"]["code"] == "stale_evidence"

    asyncio.run(_run())


def test_concurrent_identical_confirms_idempotency_replay():
    """Simulate concurrent identical confirmations with the same idempotency key.

    Both return 200 with the exact same cached payload without race conditions.
    """
    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            reset_res = await ac.post("/api/demo/reset")
            v1 = reset_res.json()["evidence_version"]

            prev_res = await ac.post(
                "/api/decisions/preview",
                json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
            )
            preview_id = prev_res.json()["preview_id"]

            confirm_payload = {
                "preview_id": preview_id,
                "expected_version": v1,
                "idempotency_key": "conc_same_idem_key",
            }

            res1, res2 = await asyncio.gather(
                ac.post("/api/decisions/confirm", json=confirm_payload),
                ac.post("/api/decisions/confirm", json=confirm_payload),
            )

            assert res1.status_code == 200
            assert res2.status_code == 200
            assert res1.json() == res2.json()
            assert res1.json()["decision_id"] == "DEC-13"
            assert res1.json()["evidence_version"].endswith(":rev_2")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2. Stale Evidence Version Rejection
# ---------------------------------------------------------------------------

def test_stale_evidence_version_rejection_across_endpoints():
    """Verify sending outdated expected_version returns 409 stale_evidence across confirm, agent, and actions."""
    stale_version = "ds_prior_outdated:rev_0"

    # 1. Decision confirmation
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    preview_id = prev_res.json()["preview_id"]
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": stale_version,
            "idempotency_key": "stale_test_confirm_key",
        },
    )
    assert confirm_res.status_code == 409
    assert confirm_res.json()["error"]["code"] == "stale_evidence"

    # 2. Agent run
    agent_res = client.post(
        "/api/agent/run",
        json={
            "message": "What is the impact?",
            "expected_version": stale_version,
        },
    )
    assert agent_res.status_code == 409
    assert agent_res.json()["error"]["code"] == "stale_evidence"

    # 3. Action creation
    action_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "stale_test_action_key",
            "expected_version": stale_version,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Test action text",
            "citations": [{"source_id": "src_permissions_ticket", "quote": "October 21, 2026"}],
            "based_on_decision_ids": ["DEC-12"],
        },
    )
    assert action_res.status_code == 409
    assert action_res.json()["error"]["code"] == "stale_evidence"


# ---------------------------------------------------------------------------
# 3. Proposal TTL Expiry
# ---------------------------------------------------------------------------

def test_proposal_ttl_expiry_returns_410():
    """Verify preview lookup or confirmation after TTL expiration returns 410 preview_expired."""
    prev_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    )
    assert prev_res.status_code == 200
    p_data = prev_res.json()
    preview_id = p_data["preview_id"]
    v1 = p_data["evidence_version"]

    # Force expiration in preview store by backdating expires_at
    store = get_preview_store()
    record = store.get(preview_id)
    record.expires_at = int(time.time() * 1000) - 5000  # Expired 5 seconds ago

    # Attempting to confirm the expired preview returns 410 preview_expired
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": preview_id,
            "expected_version": v1,
            "idempotency_key": "ttl_confirm_key_001",
        },
    )
    assert confirm_res.status_code == 410
    assert confirm_res.json()["error"]["code"] == "preview_expired"

    # Non-existent preview_id also returns 410 preview_expired
    missing_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": "prev_nonexistent_xyz",
            "expected_version": v1,
            "idempotency_key": "ttl_confirm_key_002",
        },
    )
    assert missing_res.status_code == 410
    assert missing_res.json()["error"]["code"] == "preview_expired"


# ---------------------------------------------------------------------------
# 4. Idempotency Conflict
# ---------------------------------------------------------------------------

def test_idempotency_conflict_detection():
    """Verify sending same idempotency key with mismatched payload returns 409 idempotency_conflict."""
    v1 = client.get("/api/impacts").json()["evidence_version"]

    # Decision confirm conflict
    p1 = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    ).json()["preview_id"]

    idem_key = "conflict_idem_key_001"
    ok_res = client.post(
        "/api/decisions/confirm",
        json={"preview_id": p1, "expected_version": v1, "idempotency_key": idem_key},
    )
    assert ok_res.status_code == 200

    conflict_res = client.post(
        "/api/decisions/confirm",
        json={"preview_id": "prev_different", "expected_version": v1, "idempotency_key": idem_key},
    )
    assert conflict_res.status_code == 409
    assert conflict_res.json()["error"]["code"] == "idempotency_conflict"

    # Action creation conflict
    act_key = "conflict_act_key_001"
    v2 = ok_res.json()["evidence_version"]
    base_action = {
        "idempotency_key": act_key,
        "expected_version": v2,
        "commitment_id": "com_acme_sso",
        "kind": "internal_escalation",
        "assignee_id": "person_priya",
        "body": "First version of body",
        "citations": [{"source_id": "src_permissions_ticket", "quote": "October 21, 2026"}],
        "based_on_decision_ids": ["DEC-13"],
    }
    act_ok = client.post("/api/actions", json=base_action)
    assert act_ok.status_code == 200

    altered_action = dict(base_action)
    altered_action["body"] = "Completely different body text causing conflict"
    act_conflict = client.post("/api/actions", json=altered_action)
    assert act_conflict.status_code == 409
    assert act_conflict.json()["error"]["code"] == "idempotency_conflict"


# ---------------------------------------------------------------------------
# 5. Idempotency Replay
# ---------------------------------------------------------------------------

def test_idempotency_replay_preserves_cached_response():
    """Verify sending same idempotency key with identical payload returns cached result."""
    v1 = client.get("/api/impacts").json()["evidence_version"]

    p1 = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    ).json()["preview_id"]

    idem_key = "replay_idem_key_001"
    payload = {"preview_id": p1, "expected_version": v1, "idempotency_key": idem_key}

    first = client.post("/api/decisions/confirm", json=payload)
    assert first.status_code == 200

    second = client.post("/api/decisions/confirm", json=payload)
    assert second.status_code == 200
    assert second.json() == first.json()


# ---------------------------------------------------------------------------
# 6. R1 Status Precedence
# ---------------------------------------------------------------------------

def test_r1_status_precedence_rules():
    """R1 Review Rules:

    - Commitment with missing owner without date conflict becomes needs_verification.
    - Date conflict with missing owner stays date_conflict with a warning.
    - Confirmed non-conflict with full ownership stays no_detected_conflict.
    """
    # 6a. Missing owner with no date conflict -> needs_verification
    impact_no_conflict = Impact(
        commitment_id="com_unassigned_deal",
        customer=EntityOwner(id="cust_acme", name="Acme Corp"),
        title="Unassigned Feature",
        due_at=1792778399999,
        status="no_detected_conflict",
        reasons=[],
        blockers=[],
        paths=[],
        engineering_owner=None,  # Missing owner
        account_owner=EntityOwner(id="person_maya", name="Maya Lin"),
        citations=[],
    )
    resolved_1 = apply_r1_owner_resolution(impact_no_conflict)
    assert resolved_1.status == "needs_verification"
    assert any("unresolved or ambiguous owner" in r for r in resolved_1.reasons)

    # 6b. Date conflict with missing owner -> STAYS date_conflict with warning
    impact_with_conflict = Impact(
        commitment_id="com_acme_sso",
        customer=EntityOwner(id="cust_acme", name="Acme Corp"),
        title="Enterprise SSO",
        due_at=1792778399999,
        status="date_conflict",
        reasons=["Permissions delivery Oct 28 violates Oct 23 SLA"],
        blockers=[
            Blocker(
                work_item_id="wi_permissions",
                name="Permissions Service",
                forecast_id="fc_perm_new",
                available_at=1793212800000,
                decision_id="DEC-13",
            )
        ],
        paths=[],
        engineering_owner=None,  # Missing owner
        account_owner=EntityOwner(id="person_maya", name="Maya Lin"),
        citations=[],
    )
    resolved_2 = apply_r1_owner_resolution(impact_with_conflict)
    assert resolved_2.status == "date_conflict"
    assert any("unresolved or ambiguous owner" in r for r in resolved_2.reasons)

    # 6c. Complete non-conflict with valid owners -> retains no_detected_conflict without warning
    impact_complete = Impact(
        commitment_id="com_cedar_export",
        customer=EntityOwner(id="cust_cedar", name="Cedar Technologies"),
        title="Data Export",
        due_at=1792778399999,
        status="no_detected_conflict",
        reasons=[],
        blockers=[],
        paths=[],
        engineering_owner=EntityOwner(id="person_eli", name="Eli Vance"),
        account_owner=EntityOwner(id="person_leo", name="Leo Rossi"),
        citations=[],
    )
    resolved_3 = apply_r1_owner_resolution(impact_complete)
    assert resolved_3.status == "no_detected_conflict"
    assert not any("unresolved" in r for r in resolved_3.reasons)


# ---------------------------------------------------------------------------
# 7. Rejection of Custom Backdated Effective At
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Approved: permissions service moves to Oct 28. Backdate to 2026-08-01.",
        "Approved: permissions service moves to Oct 28. Effective from yesterday.",
        "Approved: permissions service moves to Oct 28. Retroactively effective.",
        "Approved: permissions service moves to Oct 28. Effective as of 2026-09-01.",
    ],
)
def test_rejection_of_custom_backdated_effective_at(text):
    """Verify rejection of custom backdated effective_at with 422 review_required."""
    response = client.post(
        "/api/decisions/preview",
        json={"text": text},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "review_required"


# ---------------------------------------------------------------------------
# 8. Rejection of Ownership Reassignment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Approved: permissions delivery moves to Oct 28. Reassign owner to Omar.",
        "Approved: permissions delivery moves to Oct 28. Transfer ownership to Alex.",
        "Approved: permissions delivery moves to Oct 28. Change owner to Sam.",
    ],
)
def test_rejection_of_ownership_reassignment(text):
    """Verify rejection of ownership reassignment with 422 review_required."""
    response = client.post(
        "/api/decisions/preview",
        json={"text": text},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "review_required"


# ---------------------------------------------------------------------------
# 9. Restart/Reset Persistence Double
# ---------------------------------------------------------------------------

def test_restart_reset_persistence_double():
    """Verify state reset behavior:

    - Confirmed decisions and actions in cycle 1 are cleared on POST /api/demo/reset.
    - Reset generates a fresh dataset identity and restarts revision at 1.
    - Requests carrying old cycle's expected_version return 409 stale_evidence.
    """
    # Cycle 1: Advance to rev_2 and create an action
    reset_1 = client.post("/api/demo/reset")
    v1_cycle1 = reset_1.json()["evidence_version"]

    p1 = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to October 28, 2026. Owner: Priya."},
    ).json()["preview_id"]

    c1 = client.post(
        "/api/decisions/confirm",
        json={"preview_id": p1, "expected_version": v1_cycle1, "idempotency_key": "c1_key"},
    )
    v2_cycle1 = c1.json()["evidence_version"]
    assert v2_cycle1.endswith(":rev_2")

    # Save action in Cycle 1
    act_res = client.post(
        "/api/actions",
        json={
            "idempotency_key": "c1_action_key",
            "expected_version": v2_cycle1,
            "commitment_id": "com_acme_sso",
            "kind": "internal_escalation",
            "assignee_id": "person_priya",
            "body": "Cycle 1 action body",
            "citations": [{"source_id": "src_permissions_ticket", "quote": "October 21, 2026"}],
            "based_on_decision_ids": ["DEC-13"],
        },
    )
    assert act_res.status_code == 200

    # Cycle 2: Trigger demo reset
    reset_2 = client.post("/api/demo/reset")
    assert reset_2.status_code == 200
    reset_2_data = reset_2.json()
    assert reset_2_data["status"] == "reset"
    v1_cycle2 = reset_2_data["evidence_version"]

    # New dataset identity, restarted at rev_1
    assert v1_cycle2.endswith(":rev_1")
    assert v1_cycle2 != v1_cycle1
    assert reset_2_data["dataset_id"] != reset_1.json()["dataset_id"]

    # Requests carrying old cycle's version return 409 stale_evidence
    stale_check = client.post(
        "/api/agent/run",
        json={"message": "Query status", "expected_version": v2_cycle1},
    )
    assert stale_check.status_code == 409
    assert stale_check.json()["error"]["code"] == "stale_evidence"

    # Preview store from old cycle was cleared
    preview_lookup_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": p1,
            "expected_version": v1_cycle2,
            "idempotency_key": "try_confirm_old_preview",
        },
    )
    assert preview_lookup_res.status_code == 410
    assert preview_lookup_res.json()["error"]["code"] == "preview_expired"
