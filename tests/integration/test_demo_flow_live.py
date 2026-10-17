"""The judge-facing demo flow against live FalkorDB: graph view, sources, experts, decision
codes, stale-preview warnings, and the dependency toggle. Skipped when FalkorDB is unreachable."""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings import get_settings
from tests.conftest import is_falkordb_reachable

pytestmark = pytest.mark.skipif(not is_falkordb_reachable(), reason="Live FalkorDB instance is not reachable")

NOTE = ("Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
        "Owner: Priya. This replaces decision DEC-12.")


@pytest.fixture
def live_client(monkeypatch):
    monkeypatch.setenv("DEV_MOCKS", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)  # deterministic extraction
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def conflicts(client):
    return sorted(i["commitment_id"] for i in client.get("/api/impacts").json()["impacts"]
                  if i["status"] == "date_conflict")


def confirm(client, version):
    preview = client.post("/api/decisions/preview", json={"text": NOTE, "source_title": "Memo"}).json()
    res = client.post("/api/decisions/confirm", json={"preview_id": preview["preview_id"], "expected_version": version,
                                                      "idempotency_key": uuid.uuid4().hex})
    assert res.status_code == 200, res.text
    return preview, res.json()


def test_demo_flow(live_client):
    version = live_client.post("/api/demo/reset").json()["evidence_version"]
    assert conflicts(live_client) == []

    graph = live_client.get("/api/graph").json()
    assert graph["evidence_version"] == version and graph["removed_edges"] == []
    assert "MATCH" in graph["queries"]["impact_blockers"]
    titles = {s["id"]: s["title"] for s in live_client.get("/api/sources").json()["sources"]}
    assert titles["src_acme_handoff"] == "Sales handoff: Acme Corp"
    experts = live_client.get("/api/work-items/wi_permissions/experts").json()["experts"]
    assert experts[0]["name"] == "Priya Raman"

    preview, confirmed = confirm(live_client, version)
    assert preview["warnings"] == [] and preview["proposal"]["supersedes_id"] == "DEC-12"
    assert confirmed["decision_id"] == "DEC-13"
    assert conflicts(live_client) == ["com_acme_sso", "com_birch_audit"]

    # The same note again: flagged as already recorded, and pointed at the current record.
    again = live_client.post("/api/decisions/preview", json={"text": NOTE, "source_title": "Memo"}).json()
    assert any(w.startswith("already_recorded") for w in again["warnings"])

    # A note may name the runtime-created code: DEC-13 resolves from the live graph.
    later = live_client.post("/api/decisions/preview", json={
        "text": "Approved: permissions service delivery moves to November 10, 2026. Owner: Priya. "
                "This replaces decision DEC-13.", "source_title": "Memo 2"})
    assert later.status_code == 200, later.text
    assert later.json()["proposal"]["supersedes_id"] == "DEC-13" and later.json()["warnings"] == []

    body = {"from_id": "wi_identity_migration", "to_id": "wi_permissions", "present": False,
            "expected_version": confirmed["evidence_version"]}
    removed = live_client.post("/api/demo/dependency", json=body)
    assert removed.status_code == 200, removed.text
    assert conflicts(live_client) == ["com_birch_audit"]
    assert len(live_client.get("/api/graph").json()["removed_edges"]) == 1
    restored = live_client.post("/api/demo/dependency", json=dict(
        body, present=True, expected_version=removed.json()["evidence_version"]))
    assert restored.status_code == 200
    assert conflicts(live_client) == ["com_acme_sso", "com_birch_audit"]

    unknown = live_client.post("/api/demo/dependency", json=dict(
        body, from_id="wi_sso", to_id="wi_audit", expected_version=restored.json()["evidence_version"]))
    assert unknown.status_code == 422
