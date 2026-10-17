"""End-to-end verification of the graph layer through the real GraphRepository API.

Runs against a live FalkorDB (skipped when unreachable). Run with:
  PYTHONDONTWRITEBYTECODE=1 ~/.venvs/ripple-graph/bin/python -m unittest tests.graph.test_end_to_end -v

Opt-in extras (environment variables):
  RIPPLE_RESTART_TEST=1  start a throwaway container on port 6381 with a named volume, run the
                         flow, `docker restart` it and verify nothing was lost; removes both after.
  RIPPLE_TIMINGS=1       print observed timings (local Docker, not benchmarks) for the demo graph.
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "harbor"
sys.path.insert(0, str(REPO_ROOT))

try:
    from backend.app.graph.client import GraphClient
    from backend.app.graph.errors import GraphUnavailable
    from backend.app.graph.repository import GraphRepository
    from backend.app.graph.timeutil import instant_ms, to_ms
    IMPORT_ERROR = None
except ImportError as exc:
    IMPORT_ERROR = exc

SKIP_REASON = None
if IMPORT_ERROR is not None:
    SKIP_REASON = "falkordb client not importable (%s); use ~/.venvs/ripple-graph/bin/python" % IMPORT_ERROR
else:
    try:
        GraphClient().ping()
    except GraphUnavailable:
        SKIP_REASON = "FalkorDB is not reachable (set FALKORDB_HOST/FALKORDB_PORT or start the dev container)"

MINUTE = 60_000
CONTAINER = "ripple-falkordb-persist"
VOLUME = "ripple_persist_test"
IMAGE = "falkordb/falkordb:v4.22.1"
PERSIST_PORT = 6381

NOTE_BODY = ("Priya (2026-10-17 14:20 IST) in #eng-permissions: Load tests found a locking bug in the "
             "permissions service, so the old date will not hold.\n"
             "Approved: permissions service delivery moves to October 28, 2026.\n"
             "Owner: Priya.")
NOTE_QUOTE = "Approved: permissions service delivery moves to October 28, 2026."
DEPENDENCY_QUOTE = "The identity migration project depends on the permissions service."


def preview_and_now():
    preview = instant_ms("2026-10-17T14:30:00+05:30")
    return preview, preview + 5 * MINUTE


def note_source(source_id="src_priya_permissions_update"):
    preview, _ = preview_and_now()
    return {"id": source_id, "type": "chat", "title": "Priya update: permissions service slip",
            "body": NOTE_BODY, "source_timestamp": preview - 10 * MINUTE}


def note_proposal(available="2026-10-28"):
    preview, _ = preview_and_now()
    return {"work_item_id": "wi_permissions", "available_at": to_ms(available), "effective_at": preview,
            "owner_id": "person_priya", "evidence_quote": NOTE_QUOTE}


def flagged(repo, as_of):
    return sorted(i["commitment_id"] for i in repo.list_impacts(as_of)["impacts"] if i["status"] == "date_conflict")


def run_flow(test, repo):
    """Seed, confirm the canonical Oct 28 note, check history and save an Action.

    Returns a dict of everything the persistence check compares after a restart."""
    as_of = instant_ms("2026-10-17T15:00:00+05:30")
    preview, now = preview_and_now()
    dataset_id = repo.seed_demo(FIXTURES)

    baseline = repo.list_impacts(as_of)
    test.assertEqual(baseline["completeness"], {"complete": True, "truncated": False, "warnings": []})
    test.assertEqual(sorted(i["commitment_id"] for i in baseline["impacts"]),
                     ["com_acme_sso", "com_birch_audit", "com_cedar_export", "com_delta_sso"])
    test.assertEqual(flagged(repo, as_of), [])
    version0 = baseline["evidence_version"]
    test.assertEqual(version0, "%s:0" % dataset_id)

    confirmed = repo.confirm_decision(note_proposal(), note_source(), version0, "e2e-confirm-1", now)
    test.assertEqual(confirmed["evidence_version"], "%s:1" % dataset_id)
    test.assertEqual(confirmed["changed_work_item_ids"], ["wi_permissions"])
    after = repo.list_impacts(as_of)
    test.assertEqual(after["evidence_version"], confirmed["evidence_version"])
    test.assertEqual(flagged(repo, as_of), ["com_acme_sso", "com_birch_audit"])
    statuses = {i["commitment_id"]: i["status"] for i in after["impacts"]}
    test.assertEqual(statuses["com_cedar_export"], "no_detected_conflict")
    test.assertEqual(statuses["com_delta_sso"], "no_detected_conflict")

    history = repo.get_history("wi_permissions")
    old, new = history["forecasts"]
    test.assertEqual(len(history["forecasts"]), 2)
    test.assertEqual((old["id"], old["decision_id"], old["valid_to"]), ("fc_wi_permissions_baseline", "DEC-12", preview))
    test.assertEqual((new["decision_id"], new["supersedes_id"], new["valid_from"], new["valid_to"],
                      new["available_at"]), (confirmed["decision_id"], "DEC-12", preview, None, to_ms("2026-10-28")))
    test.assertIn({"source_id": "src_priya_permissions_update", "quote": NOTE_QUOTE}, new["citations"])
    test.assertEqual(old["valid_to"], new["valid_from"], "half-open intervals: no gap, no overlap")

    action = {"commitment_id": "com_acme_sso", "kind": "internal_escalation", "assignee_id": "person_priya",
              "body": "Permissions service is now forecast for 2026-10-28, after the Acme SSO due date. "
                      "Please confirm a recovery plan.",
              "citations": [{"source_id": "src_priya_permissions_update", "quote": NOTE_QUOTE},
                            {"source_id": "src_identity_plan", "quote": DEPENDENCY_QUOTE}],
              "based_on_decision_ids": [confirmed["decision_id"]]}
    saved = repo.save_action(action, confirmed["evidence_version"], "e2e-action-1", now + MINUTE)
    test.assertEqual((saved["status"], saved["evidence_version"]), ("reviewed", confirmed["evidence_version"]))
    test.assertEqual(repo.get_version(), confirmed["evidence_version"], "an Action save does not bump the version")
    listed = repo.list_actions("com_acme_sso")
    test.assertEqual(listed["evidence_version"], confirmed["evidence_version"])
    test.assertEqual(len(listed["actions"]), 1)
    stored = listed["actions"][0]
    test.assertEqual({k: stored[k] for k in action}, action)
    test.assertEqual((stored["id"], stored["status"], stored["created_at"]), (saved["action_id"], "reviewed", now + MINUTE))
    return snapshot_state(repo, as_of)


def snapshot_state(repo, as_of):
    impacts = repo.list_impacts(as_of)
    return {"version": repo.get_version(), "impacts": impacts, "history": repo.get_history("wi_permissions"),
            "actions": repo.list_actions("com_acme_sso"),
            "source": repo.get_source("src_priya_permissions_update")}


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = GraphClient(graph_name="ripple_test_" + uuid.uuid4().hex[:8])
        cls.repo = GraphRepository(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.client.delete_graph()

    def test_full_flow_then_edge_removal_proof(self):
        as_of = instant_ms("2026-10-17T15:00:00+05:30")
        run_flow(self, self.repo)
        self.assertEqual(flagged(self.repo, as_of), ["com_acme_sso", "com_birch_audit"])

        edge = ("MATCH (:WorkItem {id: 'wi_identity_migration'})-[e:DEPENDS_ON]->(:WorkItem {id: 'wi_permissions'}) ")
        self.assertEqual(self.client.read(edge + "RETURN e.source_id, e.quote"),
                         [["src_identity_plan", DEPENDENCY_QUOTE]])
        self.client.write(edge + "DELETE e")
        self.assertEqual(flagged(self.repo, as_of), ["com_birch_audit"], "Acme loses its only path; Birch keeps its own")
        acme = self.repo.get_evidence("com_acme_sso", as_of)
        self.assertEqual(acme["blockers"], [])
        self.client.write(
            "MATCH (a:WorkItem {id: 'wi_identity_migration'}), (b:WorkItem {id: 'wi_permissions'}) "
            "CREATE (a)-[:DEPENDS_ON {source_id: 'src_identity_plan', quote: $quote}]->(b)",
            {"quote": DEPENDENCY_QUOTE})
        self.assertEqual(flagged(self.repo, as_of), ["com_acme_sso", "com_birch_audit"])
        restored = self.repo.get_evidence("com_acme_sso", as_of)
        self.assertEqual([e["to_id"] for e in restored["paths"][0]["edges"]],
                         ["com_acme_sso", "wi_sso", "wi_identity_migration", "wi_permissions"])


@unittest.skipUnless(os.environ.get("RIPPLE_TIMINGS") == "1" and not SKIP_REASON, "set RIPPLE_TIMINGS=1 to print timings")
class TimingTests(unittest.TestCase):
    RUNS, WARMUP = 20, 3

    def median_ms(self, func, setup=None):
        samples = []
        for i in range(self.WARMUP + self.RUNS):
            arg = setup() if setup else None
            start = time.perf_counter()
            func(arg) if setup else func()
            elapsed = (time.perf_counter() - start) * 1000
            if i >= self.WARMUP:
                samples.append(elapsed)
        return statistics.median(samples), max(samples)

    def test_timings(self):
        client = GraphClient(graph_name="ripple_test_" + uuid.uuid4().hex[:8])
        repo = GraphRepository(client)
        self.addCleanup(client.delete_graph)
        as_of = instant_ms("2026-10-17T15:00:00+05:30")
        run_flow(self, repo)  # demo graph with the confirmed update and an Action
        rows = [("list_impacts", self.median_ms(lambda: repo.list_impacts(as_of))),
                ("get_evidence", self.median_ms(lambda: repo.get_evidence("com_acme_sso", as_of))),
                ("get_history", self.median_ms(lambda: repo.get_history("wi_permissions"))),
                ("resolve_entity", self.median_ms(lambda: repo.resolve_entity("permissions service")))]
        preview, now = preview_and_now()

        def fresh():
            repo.seed_demo(FIXTURES)
            return repo.get_version()
        confirm_ms, save_ms = [], []
        for i in range(self.WARMUP + self.RUNS):
            version = fresh()
            start = time.perf_counter()
            result = repo.confirm_decision(note_proposal(), note_source(), version, "t-confirm-%d" % i, now)
            mid = time.perf_counter()
            repo.save_action({"commitment_id": "com_acme_sso", "kind": "internal_escalation",
                              "assignee_id": "person_priya", "body": "Replan the Acme SSO delivery.",
                              "citations": [{"source_id": "src_priya_permissions_update", "quote": NOTE_QUOTE}],
                              "based_on_decision_ids": [result["decision_id"]]},
                             result["evidence_version"], "t-action-%d" % i, now)
            end = time.perf_counter()
            if i >= self.WARMUP:
                confirm_ms.append((mid - start) * 1000)
                save_ms.append((end - mid) * 1000)
        rows.append(("confirm_decision (fresh graph)", (statistics.median(confirm_ms), max(confirm_ms))))
        rows.append(("save_action (fresh graph)", (statistics.median(save_ms), max(save_ms))))
        print("\nTIMINGS local Docker, median of %d runs after %d warm-up, observed only (not benchmarks):"
              % (self.RUNS, self.WARMUP))
        for name, (median, worst) in rows:
            print("TIMING %-32s median %6.1f ms   max %6.1f ms" % (name, median, worst))


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def wait_for(client, seconds=40):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            client.ping()
            return
        except GraphUnavailable:
            time.sleep(0.5)
    raise AssertionError("FalkorDB on port %d did not come back within %ds" % (PERSIST_PORT, seconds))


@unittest.skipUnless(os.environ.get("RIPPLE_RESTART_TEST") == "1" and shutil.which("docker"),
                     "set RIPPLE_RESTART_TEST=1 (and have docker) to run the restart persistence check")
class RestartPersistenceTests(unittest.TestCase):
    def test_data_survives_container_restart(self):
        docker("rm", "-f", CONTAINER, check=False)
        docker("volume", "rm", "-f", VOLUME, check=False)
        self.addCleanup(lambda: docker("volume", "rm", "-f", VOLUME, check=False))
        self.addCleanup(lambda: docker("rm", "-f", CONTAINER, check=False))
        docker("run", "-d", "--name", CONTAINER, "-p", "%d:6379" % PERSIST_PORT, "-v",
               "%s:/var/lib/falkordb/data" % VOLUME, IMAGE)
        graph_name = "ripple_persist_" + uuid.uuid4().hex[:6]
        client = GraphClient(host="localhost", port=PERSIST_PORT, graph_name=graph_name)
        wait_for(client)

        as_of = instant_ms("2026-10-17T15:00:00+05:30")
        before = run_flow(self, GraphRepository(client))
        docker("restart", CONTAINER)

        client = GraphClient(host="localhost", port=PERSIST_PORT, graph_name=graph_name)
        wait_for(client)
        repo = GraphRepository(client)
        after = snapshot_state(repo, as_of)
        self.assertEqual(json.dumps(after, sort_keys=True), json.dumps(before, sort_keys=True))
        self.assertEqual(flagged(repo, as_of), ["com_acme_sso", "com_birch_audit"])
        self.assertEqual(client.read("MATCH (f:Forecast) RETURN count(f)"), [[len(before["history"]["forecasts"]) + 5]])
        self.assertEqual(len(after["actions"]["actions"]), 1)


if __name__ == "__main__":
    unittest.main()
