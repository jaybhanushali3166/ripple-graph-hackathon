"""Dedicated unit tests for /api/impacts endpoint.

Tests cover:
- Baseline impacts structure (4 commitments, 0 date conflicts)
- as_of parameter handling and variations (default, explicit epoch ms, zero)
- Mock header (X-Mock-Mode: true) behavior
- Completeness metadata validation (complete, truncated, warnings)
- Provenance nodes, edges, relations, and citations
- Control customer invariants (Cedar and Delta)
- Post-cutover state transitions (Acme and Birch enter date_conflict)
- R1 owner resolution rules on impacts
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_to_clean_state():
    """Reset demo state before each test to ensure isolated dataset and revision."""
    client.post("/api/demo/reset")


def test_get_impacts_baseline_structure():
    """Verify GET /api/impacts returns 4 canonical commitments with 0 date conflicts at baseline."""
    response = client.get("/api/impacts")
    assert response.status_code == 200

    data = response.json()
    assert "evidence_version" in data
    assert data["evidence_version"].endswith(":rev_1")
    assert "as_of" in data
    assert isinstance(data["as_of"], int)

    # 4 canonical commitments
    impacts = data["impacts"]
    assert len(impacts) == 4

    expected_commitments = {
        "com_acme_sso",
        "com_birch_audit",
        "com_cedar_export",
        "com_delta_sso",
    }
    actual_commitments = {imp["commitment_id"] for imp in impacts}
    assert actual_commitments == expected_commitments

    # At baseline (rev_1), 0 date conflicts
    for imp in impacts:
        assert imp["status"] == "no_detected_conflict"
        assert len(imp["blockers"]) == 0


def test_get_impacts_mock_header():
    """Verify X-Mock-Mode: true header is present when running in mock mode."""
    response = client.get("/api/impacts")
    assert response.status_code == 200
    assert response.headers.get("x-mock-mode") == "true"


def test_get_impacts_completeness_validation():
    """Verify completeness metadata adheres to agreed wire schema."""
    response = client.get("/api/impacts")
    assert response.status_code == 200

    data = response.json()
    assert "completeness" in data
    completeness = data["completeness"]
    assert completeness["complete"] is True
    assert completeness["truncated"] is False
    assert isinstance(completeness["warnings"], list)
    assert completeness["warnings"] == []


def test_get_impacts_as_of_parameter_variations():
    """Verify as_of query parameter variations are echoed in response."""
    # 1. Explicit future epoch ms
    target_as_of = 1793212800000
    res1 = client.get(f"/api/impacts?as_of={target_as_of}")
    assert res1.status_code == 200
    assert res1.json()["as_of"] == target_as_of

    # 2. Zero as_of
    res2 = client.get("/api/impacts?as_of=0")
    assert res2.status_code == 200
    assert res2.json()["as_of"] == 0

    # 3. Default omitted as_of is current server time (int)
    res3 = client.get("/api/impacts")
    assert res3.status_code == 200
    assert isinstance(res3.json()["as_of"], int)
    assert res3.json()["as_of"] > 0


def test_get_impacts_graph_paths_and_nodes_schema():
    """Verify graph paths contain structured nodes and edges with valid kinds and relations."""
    response = client.get("/api/impacts")
    assert response.status_code == 200

    allowed_kinds = {"customer", "commitment", "feature", "component", "project"}
    for imp in response.json()["impacts"]:
        assert len(imp["paths"]) >= 1
        for path in imp["paths"]:
            assert "nodes" in path and "edges" in path
            assert len(path["nodes"]) > 0
            for node in path["nodes"]:
                assert node["kind"] in allowed_kinds
                assert isinstance(node["id"], str) and node["id"]
                assert isinstance(node["label"], str) and node["label"]

            for edge in path["edges"]:
                assert isinstance(edge["from_id"], str) and edge["from_id"]
                assert isinstance(edge["to_id"], str) and edge["to_id"]
                assert isinstance(edge["relation"], str) and edge["relation"]
                assert isinstance(edge["source_id"], str) and edge["source_id"]


def test_get_impacts_citations_and_provenance():
    """Verify each impact has valid citations referencing supporting sources."""
    response = client.get("/api/impacts")
    assert response.status_code == 200

    for imp in response.json()["impacts"]:
        assert len(imp["citations"]) >= 1
        for citation in imp["citations"]:
            assert isinstance(citation["source_id"], str) and citation["source_id"].startswith("src_")
            assert isinstance(citation["quote"], str) and len(citation["quote"]) > 0


def test_get_impacts_control_customers_cedar_delta():
    """Verify control customers Cedar and Delta maintain no_detected_conflict and complete sources."""
    response = client.get("/api/impacts")
    assert response.status_code == 200

    by_id = {imp["commitment_id"]: imp for imp in response.json()["impacts"]}

    cedar = by_id["com_cedar_export"]
    assert cedar["customer"]["id"] == "cust_cedar"
    assert cedar["customer"]["name"] == "Cedar Technologies"
    assert cedar["status"] == "no_detected_conflict"
    cedar_sources = {c["source_id"] for c in cedar["citations"]}
    assert "src_cedar_handoff" in cedar_sources or "src_export_plan" in cedar_sources

    delta = by_id["com_delta_sso"]
    assert delta["customer"]["id"] == "cust_delta"
    assert delta["customer"]["name"] == "Delta Logistics"
    assert delta["status"] == "no_detected_conflict"
    delta_sources = {c["source_id"] for c in delta["citations"]}
    assert "src_delta_handoff" in delta_sources


def test_get_impacts_updated_cutover_to_revision_2():
    """Verify that bumping to revision 2 reflects date conflicts on Acme and Birch."""
    # Confirm a decision to advance revision to 2
    preview_res = client.post(
        "/api/decisions/preview",
        json={"text": "Approved: permissions service moves to Oct 28. Owner: Priya."},
    )
    p_data = preview_res.json()
    confirm_res = client.post(
        "/api/decisions/confirm",
        json={
            "preview_id": p_data["preview_id"],
            "expected_version": p_data["evidence_version"],
            "idempotency_key": "impact_cutover_test_key",
        },
    )
    assert confirm_res.status_code == 200
    v2 = confirm_res.json()["evidence_version"]
    assert v2.endswith(":rev_2")

    # Fetch updated impacts
    impacts_res = client.get("/api/impacts")
    assert impacts_res.status_code == 200
    data = impacts_res.json()
    assert data["evidence_version"] == v2

    by_id = {imp["commitment_id"]: imp for imp in data["impacts"]}

    # Acme and Birch enter date_conflict
    assert by_id["com_acme_sso"]["status"] == "date_conflict"
    assert by_id["com_birch_audit"]["status"] == "date_conflict"

    # Cedar and Delta remain controls
    assert by_id["com_cedar_export"]["status"] == "no_detected_conflict"
    assert by_id["com_delta_sso"]["status"] == "no_detected_conflict"

    # Engineering owner is Priya Sharma for date conflicts (R1 rule)
    assert by_id["com_acme_sso"]["engineering_owner"]["name"] == "Priya Sharma"
    assert by_id["com_birch_audit"]["engineering_owner"]["name"] == "Priya Sharma"

    # Blocker indicates wi_permissions
    assert len(by_id["com_acme_sso"]["blockers"]) >= 1
    blocker = by_id["com_acme_sso"]["blockers"][0]
    assert blocker["work_item_id"] == "wi_permissions"
    assert blocker["decision_id"] in ("DEC-12", "DEC-13", "dec_live_permissions_001")
