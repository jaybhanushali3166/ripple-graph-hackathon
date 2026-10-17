"""Whole-graph view, source index, "who knows what", and the demo dependency toggle."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List

from backend.app.errors import EntityNotFoundError
from backend.app.graph.errors import ReviewRequired
from backend.app.graph.repository import load_query
from backend.app.graph.seed import load_fixtures
from backend.app.schemas import (
    DependencyToggleRequest,
    DependencyToggleResponse,
    ExpertsResponse,
    GraphViewResponse,
    SourceListResponse,
)
from backend.app.services.demo_service import get_active_evidence_version, require_demo_graph
from backend.app.services.graph_client import get_graph_repository

logger = logging.getLogger("ripple.graph_view_service")

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "harbor"
DISPLAY_RELATIONS = ("HAS_COMMITMENT", "REQUIRES", "DEPENDS_ON")
# The Cypher that decides a date conflict, shown in the UI so the graph's role is inspectable.
SHOWN_QUERIES = ("impact_blockers", "impact_paths")


def _fixtures() -> Dict[str, Any]:
    return load_fixtures(str(FIXTURES_DIR))


def _fixture_dependencies() -> List[Dict[str, Any]]:
    return [r for r in _fixtures()["relationships"] if r["type"] == "DEPENDS_ON"]


def _fixture_graph() -> Dict[str, Any]:
    """The seeded graph, read from fixtures, for DEV_MOCKS mode."""
    data = _fixtures()
    nodes = ([{"id": c["id"], "label": c["name"], "kind": "customer"} for c in data["customers"]]
             + [{"id": c["id"], "label": c["title"], "kind": "commitment"}
                for c in data["commitments"] if c.get("status") == "open"]
             + [{"id": w["id"], "label": w["name"], "kind": w["kind"]} for w in data["work_items"]])
    edges = [{"from_id": r["from_id"], "to_id": r["to_id"], "relation": r["type"], "source_id": r["source_id"]}
             for r in data["relationships"] if r["type"] in DISPLAY_RELATIONS]
    return {"nodes": nodes, "edges": edges}


def _fixture_experts(work_item_id: str) -> List[Dict[str, Any]]:
    data = _fixtures()
    names = {p["id"]: p["name"] for p in data["people"]}
    teams = {t["id"]: t["name"] for t in data["teams"]}
    rels = data["relationships"]
    if work_item_id not in {w["id"] for w in data["work_items"]}:
        raise EntityNotFoundError(f"work item '{work_item_id}' not found")
    people: Dict[str, Dict[str, Any]] = {}

    def add(person_id, kind, source_id, quote, score, team=None):
        entry = people.setdefault(person_id, {"id": person_id, "name": names[person_id], "score": 0, "reasons": []})
        reason = {"kind": kind, "source_id": source_id, "quote": quote}
        if team:
            reason["team"] = team
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)
            entry["score"] += score

    for r in rels:
        if r["to_id"] == work_item_id and r["type"] in ("OWNS", "DISCUSSED"):
            add(r["from_id"], r["type"].lower(), r["source_id"], r["quote"], 3 if r["type"] == "OWNS" else 1)
    responsible = {r["from_id"] for r in rels if r["type"] == "RESPONSIBLE_FOR" and r["to_id"] == work_item_id}
    for r in rels:
        if r["type"] == "MEMBER_OF" and r["to_id"] in responsible:
            add(r["from_id"], "member_of", r["source_id"], r["quote"], 1, teams[r["to_id"]])
    return sorted(people.values(), key=lambda p: (-p["score"], p["name"]))


class GraphViewService:
    async def get_graph(self) -> GraphViewResponse:
        repo = get_graph_repository()
        if repo is None:
            graph = dict(_fixture_graph(), evidence_version=get_active_evidence_version())
        else:
            graph = await asyncio.to_thread(repo.get_graph)
        present = {(e["from_id"], e["to_id"]) for e in graph["edges"] if e["relation"] == "DEPENDS_ON"}
        removed = [{"from_id": r["from_id"], "to_id": r["to_id"], "relation": "DEPENDS_ON", "source_id": r["source_id"]}
                   for r in _fixture_dependencies() if (r["from_id"], r["to_id"]) not in present]
        queries = {name: load_query(name) for name in SHOWN_QUERIES}
        return GraphViewResponse(**graph, removed_edges=removed, queries=queries)

    async def list_sources(self) -> SourceListResponse:
        repo = get_graph_repository()
        if repo is None:
            sources = [{"id": s["id"], "type": s["type"], "title": s["title"], "source_timestamp": 0}
                       for s in _fixtures()["sources"]]
        else:
            sources = await asyncio.to_thread(repo.list_sources)
        return SourceListResponse(sources=sources)

    async def get_experts(self, work_item_id: str) -> ExpertsResponse:
        repo = get_graph_repository()
        if repo is None:
            return ExpertsResponse(evidence_version=get_active_evidence_version(), work_item_id=work_item_id,
                                   experts=_fixture_experts(work_item_id))
        return ExpertsResponse(**await asyncio.to_thread(repo.get_experts, work_item_id))

    async def set_dependency(self, request: DependencyToggleRequest) -> DependencyToggleResponse:
        """Remove or restore a recorded DEPENDS_ON edge. Only fixture edges qualify."""
        require_demo_graph()
        recorded = next((r for r in _fixture_dependencies()
                         if (r["from_id"], r["to_id"]) == (request.from_id, request.to_id)), None)
        if recorded is None:
            raise ReviewRequired("only recorded dependencies can be removed or restored in the demo")
        repo = get_graph_repository()
        if repo is None:
            # Mock mode has no graph to cut; pretending would report a change that never shows.
            raise ReviewRequired("cutting dependencies needs the live graph (DEV_MOCKS is on)")
        version = await asyncio.to_thread(repo.set_dependency, request.from_id, request.to_id, request.present,
                                          recorded["source_id"], recorded["quote"], request.expected_version)
        return DependencyToggleResponse(evidence_version=version, from_id=request.from_id, to_id=request.to_id,
                                        present=request.present)
