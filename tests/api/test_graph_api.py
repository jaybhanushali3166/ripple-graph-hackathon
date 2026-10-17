"""Graph view, source index and expertise endpoints in DEV_MOCKS mode (fixture-backed)."""
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_graph_view_lists_display_relationships():
    data = client.get("/api/graph").json()
    relations = {e["relation"] for e in data["edges"]}
    assert relations == {"HAS_COMMITMENT", "REQUIRES", "DEPENDS_ON"}
    assert {"customer", "commitment"} <= {n["kind"] for n in data["nodes"]}
    assert data["removed_edges"] == []


def test_source_index_has_titles_without_bodies():
    sources = client.get("/api/sources").json()["sources"]
    assert any(s["title"] == "Engineering sync: decision DEC-12" for s in sources)
    assert all("body" not in s for s in sources)


def test_experts_rank_owner_first():
    data = client.get("/api/work-items/wi_audit/experts").json()
    assert data["experts"][0]["id"] == "person_omar"
    assert {"person_eli"} <= {e["id"] for e in data["experts"]}


def test_experts_unknown_work_item_404():
    assert client.get("/api/work-items/wi_missing/experts").status_code == 404


def test_dependency_toggle_needs_the_live_graph_in_mock_mode():
    version = client.get("/api/impacts").json()["evidence_version"]
    res = client.post("/api/demo/dependency", json={"from_id": "wi_identity_migration", "to_id": "wi_permissions",
                                                    "present": False, "expected_version": version})
    assert res.status_code == 422


def test_demo_mutations_refuse_non_demo_graphs(monkeypatch):
    from backend.app.settings import get_settings
    monkeypatch.setenv("FALKORDB_GRAPH", "customer_prod")
    get_settings.cache_clear()
    for path, body in (("/api/demo/reset", {}), ("/api/demo/dependency", {
            "from_id": "wi_identity_migration", "to_id": "wi_permissions", "present": False, "expected_version": "x:1"})):
        assert client.post(path, json=body).status_code == 422, path
    get_settings.cache_clear()


def test_dependency_toggle_rejects_unrecorded_edges():
    version = client.get("/api/impacts").json()["evidence_version"]
    res = client.post("/api/demo/dependency", json={"from_id": "wi_sso", "to_id": "wi_audit", "present": False,
                                                    "expected_version": version})
    assert res.status_code == 422
