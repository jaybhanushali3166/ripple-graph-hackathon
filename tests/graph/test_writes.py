"""confirm_decision / save_action / list_actions against a real FalkorDB (skipped when unreachable).

Run with the venv that has the falkordb client:
  ~/.venvs/ripple-graph/bin/python -m unittest tests.graph.test_writes
Every test class gets its own randomly named graph and removes it afterwards.
"""
import copy
import json
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "harbor"
sys.path.insert(0, str(REPO_ROOT))

try:
    from backend.app.graph.client import GraphClient
    from backend.app.graph.errors import (GraphUnavailable, IdempotencyConflict, NotFound,
                                          ReviewRequired, StaleEvidence)
    from backend.app.graph.repository import GraphRepository
    from backend.app.graph.timeutil import instant_ms, to_ms
    from backend.app.graph.writes import GraphWrites
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

PREVIEW_AT = None if SKIP_REASON and IMPORT_ERROR else instant_ms("2026-10-17T14:30:00+05:30")
AS_OF = None if SKIP_REASON and IMPORT_ERROR else instant_ms("2026-10-17T15:00:00+05:30")
NOW = None if SKIP_REASON and IMPORT_ERROR else instant_ms("2026-10-17T14:35:00+05:30")
MINUTE = 60_000


def make_source(source_id="src_note_oct28", body=None):
    return {"id": source_id, "type": "note", "title": "Priya update " + source_id,
            "body": body or "Priya (2026-10-17): Permissions service slipped. Approved: new date October 28, 2026.",
            "source_timestamp": PREVIEW_AT - 5 * MINUTE}


def make_proposal(available="2026-10-28", effective_at=None, **overrides):
    proposal = {"work_item_id": "wi_permissions", "available_at": to_ms(available),
                "effective_at": effective_at if effective_at is not None else PREVIEW_AT,
                "owner_id": "person_priya", "evidence_quote": "Approved: new date October 28, 2026."}
    proposal.update(overrides)
    return proposal


def make_action(**overrides):
    action = {"commitment_id": "com_acme_sso", "kind": "internal_escalation", "assignee_id": "person_priya",
              "body": "Permissions service is forecast after the Acme SSO due date; please replan.",
              "citations": [{"source_id": "src_dec12", "quote": "DEC-12: Approved."}],
              "based_on_decision_ids": ["DEC-12"]}
    action.update(overrides)
    return action


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class WriteTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph_name = "ripple_test_" + uuid.uuid4().hex[:8]
        cls.client = GraphClient(graph_name=cls.graph_name)
        cls.repo = GraphRepository(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.client.delete_graph()

    def setUp(self):
        self.repo.seed_demo(FIXTURES)

    def snapshot(self):
        """Everything a failed write must leave untouched."""
        read = self.client.read
        return (read("MATCH (n) RETURN count(n)")[0][0], read("MATCH ()-[e]->() RETURN count(e)")[0][0],
                self.repo.get_version(),
                read("MATCH (f:Forecast) RETURN f.id, f.valid_to ORDER BY f.id"))

    def confirm(self, key="k1", proposal=None, source=None, version=None, now_ms=NOW):
        return self.repo.confirm_decision(proposal or make_proposal(), source or make_source(),
                                          version or self.repo.get_version(), key, now_ms)

    def flagged(self):
        response = self.repo.list_impacts(AS_OF)
        return sorted(i["commitment_id"] for i in response["impacts"] if i["status"] == "date_conflict")


class ConfirmDecisionTests(WriteTestCase):
    def test_canonical_oct28(self):
        before = self.repo.get_version()
        result = self.confirm()
        dataset, revision = before.split(":")
        self.assertEqual(result["evidence_version"], "%s:%d" % (dataset, int(revision) + 1))
        self.assertEqual(self.repo.get_version(), result["evidence_version"])
        self.assertEqual(result["changed_work_item_ids"], ["wi_permissions"])
        self.assertEqual(self.flagged(), ["com_acme_sso", "com_birch_audit"])

        decision_id = result["decision_id"]
        read = self.client.read
        self.assertEqual(read("MATCH (d:Decision {id: $d})-[:SUPERSEDES]->(o:Decision) RETURN o.id",
                              {"d": decision_id}), [["DEC-12"]])
        forecast = read("MATCH (d:Decision {id: $d})-[:ESTABLISHES]->(f:Forecast)<-[:HAS_FORECAST]-"
                        "(w:WorkItem) RETURN f.id, f.status, f.valid_from, f.valid_to, f.available_at, f.recorded_at,"
                        " w.id", {"d": decision_id})
        revises = read("MATCH (:Decision {id: $d})-[:REVISES]->(w:WorkItem) RETURN count(w)", {"d": decision_id})[0][0]
        self.assertEqual(len(forecast), 1)
        _, status, valid_from, valid_to, available_at, recorded_at, wi_id = forecast[0]
        self.assertEqual((status, valid_from, valid_to, available_at, recorded_at, wi_id, revises),
                         ("accepted", PREVIEW_AT, None, to_ms("2026-10-28"), NOW, "wi_permissions", 1))
        old = read("MATCH (f:Forecast {id: 'fc_wi_permissions_baseline'}) RETURN f.valid_to")
        self.assertEqual(old, [[PREVIEW_AT]])
        for label in ("Decision", "Forecast"):
            quotes = read("MATCH (n:%s)-[e:SUPPORTED_BY]->(:Source {id: 'src_note_oct28'}) RETURN e.quote" % label)
            self.assertEqual(quotes, [["Approved: new date October 28, 2026."]])
        self.assertEqual(read("MATCH (r:RequestRecord) RETURN r.operation, r.idempotency_key, r.dataset_id"),
                         [["confirm_decision", "k1", dataset]])

    def test_other_dates_match_expected(self):
        expected = json.loads((FIXTURES / "expected" / "updates.json").read_text(encoding="utf-8"))
        for update in expected["updates"]:
            self.repo.seed_demo(FIXTURES)
            day = update["new_available_at"]
            self.confirm(key=update["id"], proposal=make_proposal(day), source=make_source("src_note_" + day))
            self.assertEqual(self.flagged(), update["flagged_commitment_ids"], update["id"])

    def test_second_update_supersedes_the_generated_decision(self):
        first = self.confirm()
        later = PREVIEW_AT + 5 * MINUTE
        second = self.confirm(key="k2", proposal=make_proposal("2026-11-10", effective_at=later,
                                                               evidence_quote="Approved: new date October 28, 2026."),
                              source=make_source("src_note_nov10"), version=first["evidence_version"],
                              now_ms=later + MINUTE)
        self.assertEqual(self.client.read("MATCH (:Decision {id: $d})-[:SUPERSEDES]->(o:Decision) RETURN o.id",
                                          {"d": second["decision_id"]}), [[first["decision_id"]]])
        self.assertEqual(self.client.read("MATCH (f:Forecast {valid_to: $t}) RETURN count(f)", {"t": later}), [[1]])
        self.assertEqual(self.flagged(), ["com_acme_sso", "com_birch_audit", "com_delta_sso"])

    def test_supersedes_id_matching_active_decision_is_accepted(self):
        self.confirm(proposal=make_proposal(supersedes_id="DEC-12"))
        self.assertEqual(self.flagged(), ["com_acme_sso", "com_birch_audit"])

    def test_replay_returns_same_result_without_new_nodes(self):
        version = self.repo.get_version()
        first = self.confirm(version=version)
        after = self.snapshot()
        self.assertEqual(self.confirm(version=version, now_ms=NOW + 10 * MINUTE), first)
        self.assertEqual(self.snapshot(), after)

    def test_same_key_different_payload_conflicts(self):
        version = self.repo.get_version()
        self.confirm(version=version)
        after = self.snapshot()
        with self.assertRaises(IdempotencyConflict):
            self.confirm(version=version, proposal=make_proposal("2026-11-10"))
        self.assertEqual(self.snapshot(), after)

    def test_stale_version_creates_nothing(self):
        stale = self.repo.get_version()
        self.confirm()
        after = self.snapshot()
        with self.assertRaises(StaleEvidence):
            self.confirm(key="k2", version=stale, proposal=make_proposal(effective_at=PREVIEW_AT + MINUTE),
                         source=make_source("src_other"))
        self.assertEqual(self.snapshot(), after)
        with self.assertRaises(StaleEvidence):
            self.confirm(key="k3", version="not-a-version")
        with self.assertRaises(StaleEvidence):
            self.confirm(key="k4", version="deadbeef:0", proposal=make_proposal(effective_at=PREVIEW_AT + MINUTE),
                         source=make_source("src_other"))

    def test_stale_version_wins_over_validation_errors(self):
        stale = self.repo.get_version()
        self.confirm()
        before = self.snapshot()
        with self.assertRaises(StaleEvidence):  # same note again: also a no-op, but the view is stale
            self.confirm(key="k2", version=stale)
        with self.assertRaises(StaleEvidence):
            self.confirm(key="k3", version=stale, proposal=make_proposal(owner_id="person_lena"))
        self.assertEqual(self.snapshot(), before)

    def test_decision_summary_is_readable(self):
        result = self.confirm()
        self.assertEqual(self.client.read("MATCH (d:Decision {id: $d}) RETURN d.summary", {"d": result["decision_id"]}),
                         [["Permissions service delivery set to 2026-10-28 (IST)"]])

    def test_repeat_of_the_same_note_is_rejected(self):
        self.confirm()
        version = self.repo.get_version()
        before = self.snapshot()
        with self.assertRaises(ReviewRequired):
            self.confirm(key="k2", version=version, proposal=make_proposal(effective_at=PREVIEW_AT + MINUTE),
                         now_ms=NOW + MINUTE)
        self.assertEqual(self.snapshot(), before)

    def test_update_to_the_current_date_is_rejected(self):
        self.assert_rejected(ReviewRequired, proposal=make_proposal("2026-10-21"), source=make_source("src_same"))

    def test_existing_decision_or_forecast_id_is_rejected(self):
        first = self.confirm()
        later = PREVIEW_AT + 5 * MINUTE
        self.confirm(key="k2", version=first["evidence_version"], now_ms=later + MINUTE,
                     proposal=make_proposal("2026-11-10", effective_at=later), source=make_source("src_nov"))
        before = self.snapshot()
        with self.assertRaises(ReviewRequired):  # Oct 28 from the same source again hashes to the first IDs
            self.confirm(key="k3", version=before[2], now_ms=later + 3 * MINUTE,
                         proposal=make_proposal("2026-10-28", effective_at=later + 2 * MINUTE))
        self.assertEqual(self.snapshot(), before)

    def test_cypher_gate_alone_blocks_every_mutation(self):
        """Run the write statement with a wrong revision, bypassing Python validation."""
        from backend.app.graph.repository import load_query
        before = self.snapshot()
        dataset = before[2].split(":")[0]
        params = {"dataset": dataset, "expected_revision": 99, "work_item_id": "wi_permissions",
                  "effective_at": PREVIEW_AT, "available_at": 1, "now": NOW, "source_id": "src_gate",
                  "source_type": "note", "source_title": "t", "source_body": "b", "source_timestamp": 1,
                  "content_hash": "h", "quote": "q", "forecast_id": "fc_gate", "decision_id": "dec_gate",
                  "summary": "s", "request_id": "req_gate", "key": "k", "request_hash": "h", "result_json": "{}"}
        written = self.client.write(load_query("confirm_decision"), params)
        self.assertEqual((written["rows"], written["nodes_created"], written["relationships_created"]), ([], 0, 0))
        self.assertEqual(self.snapshot(), before)

    def assert_rejected(self, error, **kwargs):
        before = self.snapshot()
        with self.assertRaises(error):
            self.confirm(**kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_requests_leave_graph_unchanged(self):
        cases = {
            "unknown work item": (NotFound, dict(proposal=make_proposal(work_item_id="wi_nope"))),
            "wrong owner": (ReviewRequired, dict(proposal=make_proposal(owner_id="person_lena"))),
            "quote not in body": (ReviewRequired, dict(proposal=make_proposal(evidence_quote="Approved: Dec 31."))),
            "effective_at equals valid_from": (
                ReviewRequired, dict(proposal=make_proposal(effective_at=instant_ms("2026-10-01T10:00:00+05:30")))),
            "effective_at before valid_from": (
                ReviewRequired, dict(proposal=make_proposal(effective_at=instant_ms("2026-09-01T10:00:00+05:30")))),
            "effective_at in the future": (
                ReviewRequired, dict(proposal=make_proposal(effective_at=NOW + MINUTE))),
            "wrong supersedes_id": (
                ReviewRequired, dict(proposal=make_proposal(supersedes_id="dec_baseline_wi_sso"))),
            "source id with different content": (
                ReviewRequired, dict(source=make_source("src_dec12", body="DEC-12: changed. Approved: new date October 28, 2026."))),
        }
        for name, (error, kwargs) in cases.items():
            with self.subTest(name):
                self.assert_rejected(error, **kwargs)

    def test_no_active_forecast_requires_review(self):
        self.client.write("MATCH (f:Forecast {id: 'fc_wi_permissions_baseline'}) SET f.valid_to = $t",
                          {"t": PREVIEW_AT - MINUTE})
        self.assert_rejected(ReviewRequired)

    def test_two_active_forecasts_require_review(self):
        self.client.write("MATCH (w:WorkItem {id: 'wi_permissions'}) CREATE (w)-[:HAS_FORECAST]->"
                          "(:Forecast {id: 'fc_dup', status: 'accepted', valid_from: 1, available_at: 1})")
        self.assert_rejected(ReviewRequired)

    def test_missing_or_ambiguous_owner_requires_review(self):
        self.client.write("MATCH (w:WorkItem {id: 'wi_permissions'}) CREATE (:Person {id: 'p2', name: 'P2'})"
                          "-[:OWNS]->(w)")
        self.assert_rejected(ReviewRequired)
        self.client.write("MATCH (:Person)-[o:OWNS]->(:WorkItem {id: 'wi_permissions'}) DELETE o")
        self.assert_rejected(ReviewRequired)

    def test_past_delivery_date_is_allowed(self):
        self.confirm(proposal=make_proposal("2026-10-05"), source=make_source("src_past"))
        self.assertEqual(self.flagged(), [])

    def test_same_source_can_be_reused_with_identical_content(self):
        first = self.confirm()
        later = PREVIEW_AT + 5 * MINUTE
        self.confirm(key="k2", version=first["evidence_version"], now_ms=later + MINUTE,
                     proposal=make_proposal("2026-11-10", effective_at=later))
        self.assertEqual(self.client.read("MATCH (s:Source {id: 'src_note_oct28'}) RETURN count(s)"), [[1]])

    def test_overlapping_confirms_gate_on_the_revision(self):
        """Both writers pass validation and the version check before either writes."""
        version = self.repo.get_version()
        original = GraphWrites._require_current
        barrier = threading.Barrier(2)

        def synced(writes, expected):
            original(writes, expected)
            barrier.wait(timeout=10)
        outcomes = {}

        def attempt(name, available, source_id):
            repo = GraphRepository(GraphClient(graph_name=self.graph_name))
            try:
                outcomes[name] = repo.confirm_decision(make_proposal(available), make_source(source_id),
                                                       version, "key_" + name, NOW)
            except Exception as exc:  # noqa: BLE001 - the outcome is asserted below
                outcomes[name] = exc
        with mock.patch.object(GraphWrites, "_require_current", synced):
            threads = [threading.Thread(target=attempt, args=("a", "2026-10-28", "src_a")),
                       threading.Thread(target=attempt, args=("b", "2026-11-10", "src_b"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        successes = [o for o in outcomes.values() if isinstance(o, dict)]
        failures = [o for o in outcomes.values() if isinstance(o, Exception)]
        self.assertEqual((len(successes), len(failures)), (1, 1), outcomes)
        self.assertIsInstance(failures[0], StaleEvidence)
        dataset, revision = version.split(":")
        self.assertEqual(self.repo.get_version(), "%s:%d" % (dataset, int(revision) + 1))
        self.assertEqual(self.client.read("MATCH (d:Decision)-[:SUPERSEDES]->(:Decision {id: 'DEC-12'}) RETURN count(d)"),
                         [[1]])
        self.assertEqual(self.client.read("MATCH (r:RequestRecord) RETURN count(r)"), [[1]])
        self.assertEqual(self.client.read("MATCH (f:Forecast {status: 'accepted'}) WHERE f.valid_to IS NULL "
                                          "AND f.id STARTS WITH 'fc_' AND NOT f.id ENDS WITH '_baseline' "
                                          "RETURN count(f)"), [[1]])

    def commit_racer_after_version_check(self, racer):
        """Patch _require_current so `racer` commits right after the first caller's version check passes."""
        original = GraphWrites._require_current
        fired = []

        def check_then_race(writes, expected):
            original(writes, expected)
            if not fired:
                fired.append(True)
                racer(GraphRepository(GraphClient(graph_name=self.graph_name)))
        return mock.patch.object(GraphWrites, "_require_current", check_then_race)

    def test_losing_a_race_before_validation_is_stale_not_review(self):
        """The loser validates against the winner's forecast (valid_from == its effective_at)."""
        version = self.repo.get_version()
        winner = {}
        with self.commit_racer_after_version_check(lambda repo: winner.update(repo.confirm_decision(
                make_proposal("2026-11-10"), make_source("src_b"), version, "key_b", NOW))):
            with self.assertRaises(StaleEvidence) as caught:
                self.confirm("key_a", source=make_source("src_a"), version=version)
        self.assertEqual(caught.exception.details["current_version"], winner["evidence_version"])
        self.assertEqual(self.client.read("MATCH (r:RequestRecord) RETURN count(r)"), [[1]])

    def test_identical_racer_replays_the_winners_result(self):
        version = self.repo.get_version()
        winner = {}
        with self.commit_racer_after_version_check(lambda repo: winner.update(repo.confirm_decision(
                make_proposal(), make_source(), version, "k1", NOW))):
            result = self.confirm("k1", version=version)
        self.assertEqual(result, winner)
        self.assertEqual(self.client.read("MATCH (r:RequestRecord) RETURN count(r)"), [[1]])

    def test_genuine_review_error_is_unchanged_without_a_race(self):
        with self.assertRaises(ReviewRequired):
            self.confirm(proposal=make_proposal(owner_id="person_lena"))

    def test_replay_confirm_returns_stored_result_without_writing(self):
        version = self.repo.get_version()
        self.assertIsNone(self.repo.replay_confirm(make_proposal(), make_source(), version, "k1"))
        result = self.confirm("k1", version=version)
        before = self.snapshot()
        self.assertEqual(self.repo.replay_confirm(make_proposal(), make_source(), version, "k1"), result)
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(IdempotencyConflict):
            self.repo.replay_confirm(make_proposal("2026-11-10"), make_source(), version, "k1")


class ActionTests(WriteTestCase):
    def save(self, key="a1", action=None, version=None, now_ms=NOW):
        return self.repo.save_action(action or make_action(), version or self.repo.get_version(), key, now_ms)

    def test_save_then_list(self):
        version = self.repo.get_version()
        result = self.save(version=version)
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(result["evidence_version"], version)
        self.assertEqual(result["created_at"], NOW)
        self.assertEqual(self.repo.get_version(), version, "an Action save must not bump the revision")
        listed = self.repo.list_actions("com_acme_sso")
        self.assertEqual(listed["evidence_version"], version)
        self.assertEqual(listed["actions"], [{
            "id": result["action_id"], "commitment_id": "com_acme_sso", "kind": "internal_escalation",
            "assignee_id": "person_priya", "body": make_action()["body"],
            "citations": make_action()["citations"], "based_on_decision_ids": ["DEC-12"],
            "status": "reviewed", "evidence_version": version, "created_at": NOW}])
        self.assertEqual(self.repo.list_actions("com_birch_audit")["actions"], [])

    def test_list_is_sorted_by_created_at(self):
        late = self.save(key="late", now_ms=NOW + 10 * MINUTE)
        early = self.save(key="early", now_ms=NOW)
        ids = [a["id"] for a in self.repo.list_actions("com_acme_sso")["actions"]]
        self.assertEqual(ids, [early["action_id"], late["action_id"]])

    def test_replay_is_identical_even_after_knowledge_change(self):
        version = self.repo.get_version()
        first = self.save(version=version)
        count = self.snapshot()[0]
        self.assertEqual(self.save(version=version, now_ms=NOW + MINUTE), first)
        self.assertEqual(self.snapshot()[0], count)
        self.repo.confirm_decision(make_proposal(), make_source(), version, "k1", NOW)
        self.assertEqual(self.save(version=version, now_ms=NOW + 2 * MINUTE), first)

    def test_overlapping_identical_saves_create_one_action(self):
        """Both writers pass the replay and version checks before either writes."""
        version = self.repo.get_version()
        original = GraphWrites._require_current
        barrier = threading.Barrier(2)

        def synced(writes, expected):
            original(writes, expected)
            barrier.wait(timeout=10)
        outcomes = {}

        def attempt(name):
            repo = GraphRepository(GraphClient(graph_name=self.graph_name))
            try:
                outcomes[name] = repo.save_action(make_action(), version, "same_key", NOW)
            except Exception as exc:  # noqa: BLE001 - the outcome is asserted below
                outcomes[name] = exc
        with mock.patch.object(GraphWrites, "_require_current", synced):
            threads = [threading.Thread(target=attempt, args=(name,)) for name in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(len(outcomes), 2, outcomes)
        self.assertTrue(all(isinstance(o, dict) for o in outcomes.values()), outcomes)
        self.assertEqual(outcomes["a"], outcomes["b"])
        self.assertEqual(self.client.read("MATCH (a:Action) RETURN count(a)"), [[1]])
        self.assertEqual(self.client.read("MATCH (r:RequestRecord) RETURN count(r)"), [[1]])
        self.assertEqual(self.client.read("MATCH (:Action)-[e:BASED_ON]->(:Decision) RETURN count(e)"), [[1]])
        self.assertEqual(self.repo.get_version(), version)

    def test_overlapping_saves_with_different_payloads_conflict(self):
        version = self.repo.get_version()
        original = GraphWrites._require_current
        barrier = threading.Barrier(2)

        def synced(writes, expected):
            original(writes, expected)
            barrier.wait(timeout=10)
        outcomes = {}

        def attempt(name):
            repo = GraphRepository(GraphClient(graph_name=self.graph_name))
            try:
                outcomes[name] = repo.save_action(make_action(body="body " + name), version, "same_key", NOW)
            except Exception as exc:  # noqa: BLE001 - the outcome is asserted below
                outcomes[name] = exc
        with mock.patch.object(GraphWrites, "_require_current", synced):
            threads = [threading.Thread(target=attempt, args=(name,)) for name in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        successes = [o for o in outcomes.values() if isinstance(o, dict)]
        failures = [o for o in outcomes.values() if isinstance(o, Exception)]
        self.assertEqual((len(successes), len(failures)), (1, 1), outcomes)
        self.assertIsInstance(failures[0], IdempotencyConflict)
        self.assertEqual(self.client.read("MATCH (a:Action) RETURN count(a)"), [[1]])
        self.assertEqual(self.client.read("MATCH (r:RequestRecord) RETURN count(r)"), [[1]])

    def test_same_key_different_payload_conflicts(self):
        version = self.repo.get_version()
        self.save(version=version)
        with self.assertRaises(IdempotencyConflict):
            self.save(version=version, action=make_action(body="different body"))

    def test_stale_version_is_rejected(self):
        stale = self.repo.get_version()
        self.repo.confirm_decision(make_proposal(), make_source(), stale, "k1", NOW)
        before = self.snapshot()
        with self.assertRaises(StaleEvidence):
            self.save(key="a2", version=stale)
        self.assertEqual(self.snapshot(), before)

    def test_saved_action_keeps_its_evidence_version_after_a_confirm(self):
        old_version = self.repo.get_version()
        self.save(version=old_version)
        confirmed = self.repo.confirm_decision(make_proposal(), make_source(), old_version, "k1", NOW)
        listed = self.repo.list_actions("com_acme_sso")
        self.assertEqual(listed["evidence_version"], confirmed["evidence_version"])
        self.assertEqual(listed["actions"][0]["evidence_version"], old_version)
        self.assertNotEqual(old_version, listed["evidence_version"])

    def test_stale_version_wins_over_invalid_action(self):
        stale = self.repo.get_version()
        self.repo.confirm_decision(make_proposal(), make_source(), stale, "k1", NOW)
        with self.assertRaises(StaleEvidence):
            self.save(key="a2", version=stale, action=make_action(kind="tweet"))

    def test_invalid_actions_write_nothing(self):
        cases = {
            "unknown commitment": (NotFound, make_action(commitment_id="com_nope")),
            "unknown assignee": (NotFound, make_action(assignee_id="person_nope")),
            "null assignee": (NotFound, make_action(assignee_id=None)),
            "unknown decision": (NotFound, make_action(based_on_decision_ids=["DEC-404"])),
            "unknown citation source": (NotFound, make_action(citations=[{"source_id": "src_nope", "quote": "x"}])),
            "bad kind": (ReviewRequired, make_action(kind="tweet")),
            "empty body": (ReviewRequired, make_action(body="  ")),
            "no citations": (ReviewRequired, make_action(citations=[])),
            "no decisions": (ReviewRequired, make_action(based_on_decision_ids=[])),
            "bad quote": (ReviewRequired, make_action(
                citations=[{"source_id": "src_dec12", "quote": "DEC-12: Rejected."}])),
        }
        for name, (error, action) in cases.items():
            with self.subTest(name):
                before = self.snapshot()
                with self.assertRaises(error):
                    self.save(key="bad_" + name, action=action)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.repo.list_actions("com_acme_sso")["actions"], [])

    def test_duplicate_decision_ids_are_collapsed(self):
        self.save(action=make_action(based_on_decision_ids=["DEC-12", "DEC-12"]))
        self.assertEqual(self.repo.list_actions("com_acme_sso")["actions"][0]["based_on_decision_ids"], ["DEC-12"])

    def test_list_actions_unknown_commitment(self):
        with self.assertRaises(NotFound):
            self.repo.list_actions("com_nope")


if __name__ == "__main__":
    unittest.main()
