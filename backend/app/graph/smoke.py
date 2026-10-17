"""Seed the demo graph and print the four baseline statuses plus one source.

Run from the repo root:
  ~/.venvs/ripple-graph/bin/python -m backend.app.graph.smoke
Reads FALKORDB_HOST / FALKORDB_PORT / FALKORDB_PASSWORD / RIPPLE_GRAPH_NAME (default ripple_demo).
"""
import sys
from datetime import datetime
from pathlib import Path

from .client import GraphClient
from .errors import GraphError
from .repository import GraphRepository
from .timeutil import IST

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "harbor"


def main():
    repo = GraphRepository(GraphClient())
    try:
        repo.seed_demo(FIXTURES_DIR)
        as_of = round(datetime.now(IST).timestamp() * 1000)
        print("graph %s, evidence_version %s" % (repo.client.graph_name, repo.get_version()))
        response = repo.list_impacts(as_of)
    except GraphError as exc:
        print("graph error: %s" % exc.message, file=sys.stderr)
        return 1
    for impact in response["impacts"]:
        eng, acct = impact["engineering_owner"], impact["account_owner"]
        print("%-18s %-20s eng=%-14s account=%s" % (
            impact["commitment_id"], impact["status"], eng and eng["id"], acct and acct["id"]))
    print("completeness:", response["completeness"])
    source = repo.get_source("src_dec12")
    print("\nsource %s (%s, hash %s...)\n%s" % (source["id"], source["type"], source["content_hash"][:12], source["body"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
