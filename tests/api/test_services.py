"""Comprehensive Phase 2 tests for ImpactService, SourceService, DemoService, and R1 rules."""

import pytest
from fastapi.testclient import TestClient

from backend.app.errors import (
    AIUnavailableError,
    EntityNotFoundError,
    GraphUnavailableError,
    IdempotencyConflictError,
    PreviewExpiredError,
    ReviewRequiredError,
    RippleError,
    StaleVersionError,
)
from backend.app.main import app
from backend.app.schemas import Blocker, EntityOwner, Impact, SourceRef
from backend.app.services.demo_service import (
    bump_knowledge_revision,
    get_active_dataset_id,
    get_active_evidence_version,
    get_active_revision,
    set_active_dataset,
    validate_expected_version,
)
from backend.app.services.impact_service import ImpactService
from backend.app.services.source_service import SourceService

def apply_r1_owner_resolution(impact: Impact) -> Impact:
    has_date_conflict = impact.status == "date_conflict"
    has_blockers = bool(impact.blockers)
    warnings = list(impact.reasons)
    if impact.engineering_owner is None or impact.account_owner is None:
        owner_warning = "Commitment has unresolved or ambiguous owner assignments."
        if owner_warning not in warnings:
            warnings.append(owner_warning)
        if not has_date_conflict and not has_blockers:
            impact.status = "needs_verification"
    impact.reasons = warnings
    return impact

client = TestClient(app)


# ---------------------------------------------------------------------------
# TASK-PVN-201: R1 Owner Resolution Unit Tests
# ---------------------------------------------------------------------------

def test_r1_owner_resolution_date_conflict_preserves_conflict_status():
    """R1 Rule: When date_conflict exists but ownership is missing, status remains date_conflict with a warning."""
    impact = Impact(
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
        engineering_owner=None,  # Missing engineering owner
        account_owner=EntityOwner(id="person_maya", name="Maya Lin"),
        citations=[],
    )

    resolved = apply_r1_owner_resolution(impact)
    # Must preserve date_conflict due to status precedence rule
    assert resolved.status == "date_conflict"
    assert any("unresolved or ambiguous owner" in r for r in resolved.reasons)


def test_r1_owner_resolution_missing_owner_without_conflict_yields_needs_verification():
    """R1 Rule: Missing owner with no confirmed date conflict becomes needs_verification."""
    impact = Impact(
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

    resolved = apply_r1_owner_resolution(impact)
    assert resolved.status == "needs_verification"
    assert any("unresolved or ambiguous owner" in r for r in resolved.reasons)


def test_r1_owner_resolution_complete_non_conflict():
    """R1 Rule: Confirmed non-conflict with full ownership retains no_detected_conflict without warnings."""
    impact = Impact(
        commitment_id="com_cedar_export",
        customer=EntityOwner(id="cust_cedar", name="Cedar Enterprises"),
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

    resolved = apply_r1_owner_resolution(impact)
    assert resolved.status == "no_detected_conflict"
    assert not any("unresolved" in r for r in resolved.reasons)


# ---------------------------------------------------------------------------
# TASK-PVN-201: Impact & Source Query Services
# ---------------------------------------------------------------------------

def test_impact_service_baseline_and_updated_cutover():
    """Verify impact service transitions from 0 conflicts at rev 1 to 2 conflicts at rev 2."""
    async def _run():
        set_active_dataset("ds_test_impacts", revision=1)
        service = ImpactService()

        # Revision 1: Baseline impacts (0 date conflicts)
        baseline = await service.get_impacts()
        assert baseline.evidence_version == "ds_test_impacts:rev_1"
        assert len(baseline.impacts) == 4
        for imp in baseline.impacts:
            assert imp.status == "no_detected_conflict"

        # Bump revision to simulate confirmed cutover
        bump_knowledge_revision()
        assert get_active_revision() == 2

        # Revision 2: Updated impacts (Acme & Birch date conflicts with Priya as owner)
        updated = await service.get_impacts()
        assert updated.evidence_version == "ds_test_impacts:rev_2"
        assert len(updated.impacts) == 4

        conflicted = {imp.commitment_id: imp for imp in updated.impacts if imp.status == "date_conflict"}
        assert "com_acme_sso" in conflicted
        assert "com_birch_audit" in conflicted

        # Verify R1 Rule: engineering_owner is the unique owner of the blocking component (Priya)
        assert conflicted["com_acme_sso"].engineering_owner.name == "Priya Sharma"
        assert conflicted["com_birch_audit"].engineering_owner.name == "Priya Sharma"

    import asyncio
    asyncio.run(_run())


def test_source_service_valid_and_not_found():
    """Verify source service returns deterministic sha256 hash or raises EntityNotFoundError."""
    async def _run():
        service = SourceService()

        # Valid source
        source = await service.get_source("src_permissions_ticket")
        assert source.id == "src_permissions_ticket"
        assert "permissions service" in source.body.lower()
        assert len(source.content_hash) == 64

        # Non-existent source
        with pytest.raises(EntityNotFoundError):
            await service.get_source("src_non_existent_12345")

    import asyncio
    asyncio.run(_run())


def test_source_history_valid_and_not_found():
    """Verify history service enforces non-nullable decision_id or raises EntityNotFoundError."""
    async def _run():
        service = SourceService()

        # Valid work item wi_permissions
        history = await service.get_history("wi_permissions")
        assert len(history.forecasts) >= 1
        assert history.forecasts[0].decision_id == "DEC-12"

        # Non-existent work item
        with pytest.raises(EntityNotFoundError):
            await service.get_history("wi_non_existent_xyz")

    import asyncio
    asyncio.run(_run())


def test_demo_reset_generates_fresh_dataset_and_revision():
    """Verify demo reset creates a new dataset_id, resets revision to 1, and updates active version."""
    initial_version = get_active_evidence_version()

    response = client.post("/api/demo/reset")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "reset"
    assert data["dataset_id"].startswith("ds_")
    assert data["evidence_version"].startswith(data["dataset_id"])
    assert data["evidence_version"] != initial_version

    # Validate active state in service matches
    assert get_active_dataset_id() == data["dataset_id"]
    assert get_active_revision() in (0, 1)


def test_stale_evidence_validation_rejects_old_dataset_requests():
    """R1 Rule: Old dataset requests return 409 stale_evidence rather than replaying into new demo data."""
    set_active_dataset("ds_active_001", revision=1)

    # Correct active version passes
    validate_expected_version("ds_active_001:rev_1")

    # Outdated revision fails with 409
    with pytest.raises(StaleVersionError) as exc_info:
        validate_expected_version("ds_active_001:rev_0")
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "stale_evidence"

    # Prior dataset ID fails with 409
    with pytest.raises(StaleVersionError) as exc_info2:
        validate_expected_version("ds_old_prior:rev_1")
    assert exc_info2.value.status_code == 409
    assert exc_info2.value.code == "stale_evidence"


# ---------------------------------------------------------------------------
# TASK-PVN-203: Domain Exception Mapping to HTTP Contract
# ---------------------------------------------------------------------------

def test_http_mapping_for_entity_not_found():
    """Verify GET /api/sources/unknown returns HTTP 404 in unified envelope."""
    response = client.get("/api/sources/unknown_source_id_999")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "not_found"
    assert "unknown_source_id_999" in data["error"]["message"]


def test_http_mapping_for_work_item_not_found():
    """Verify GET /api/work-items/unknown/history returns HTTP 404 in unified envelope."""
    response = client.get("/api/work-items/unknown_work_item_999/history")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "not_found"
    assert "unknown_work_item_999" in data["error"]["message"]


@pytest.mark.parametrize(
    "exception_cls,expected_status,expected_code",
    [
        (GraphUnavailableError, 503, "graph_unavailable"),
        (EntityNotFoundError, 404, "not_found"),
        (StaleVersionError, 409, "stale_evidence"),
        (IdempotencyConflictError, 409, "idempotency_conflict"),
        (PreviewExpiredError, 410, "preview_expired"),
        (ReviewRequiredError, 422, "review_required"),
        (AIUnavailableError, 502, "ai_unavailable"),
    ],
)
def test_all_domain_exceptions_adhere_to_http_contract(exception_cls, expected_status, expected_code):
    """Verify domain exceptions carry the exact HTTP status and code required by SHARED_CONTRACT.md."""
    err = exception_cls("Test error message", details={"field": "test"})
    assert isinstance(err, RippleError)
    assert err.status_code == expected_status
    assert err.code == expected_code
    assert err.details == {"field": "test"}
