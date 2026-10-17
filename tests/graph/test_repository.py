"""GraphRepository tests against a real FalkorDB (skipped when it is unreachable).

The committed fixtures are used only as assertions here: expected/*.json says what the graph
must answer, and the graph itself is loaded through the seed helper. Run with the venv that
has the falkordb client, for example:
  ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
Connection settings come from FALKORDB_HOST / FALKORDB_PORT / FALKORDB_PASSWORD.
"""
import json
import shutil
import statistics
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "harbor"
sys.path.insert(0, str(REPO_ROOT))  # lets `backend.app.graph` import without package manifests

try:
    from backend.app.graph.client import GraphClient
    from backend.app.graph.errors import FixtureError, GraphError, GraphUnavailable, InconsistentRead, NotFound
    from backend.app.graph.repository import GraphRepository, warning_code
    from backend.app.graph.seed import apply_scenario, load_fixtures
    from backend.app.graph.timeutil import instant_ms
    IMPORT_ERROR = None
except ImportError as exc:  # falkordb/redis not installed in this interpreter
    IMPORT_ERROR = exc

SKIP_REASON = None
if IMPORT_ERROR is not None:
    SKIP_REASON = "falkordb client not importable (%s); use ~/.venvs/ripple-graph/bin/python" % IMPORT_ERROR
else:
    try:
        GraphClient().ping()
    except GraphUnavailable:
        SKIP_REASON = "FalkorDB is not reachable (set FALKORDB_HOST/FALKORDB_PORT or start the dev container)"


def load(rel):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def summarize(impact):
    """Project an Impact onto the keys the expected/*.json files assert."""
    codes = sorted({warning_code(r) for r in impact["reasons"] if warning_code(r)})
    return {"customer_id": impact["customer"]["id"] or None, "status": impact["status"],
            "blocker_work_item_ids": sorted(b["work_item_id"] for b in impact["blockers"]),
            "engineering_owner_id": (impact["engineering_owner"] or {}).get("id"),
            "account_owner_id": (impact["account_owner"] or {}).get("id"),
            "warnings": codes, "truncated": "depth_limit_exceeded" in codes}


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class RepositoryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = GraphClient(graph_name="ripple_test_" + uuid.uuid4().hex[:8])
        cls.repo = GraphRepository(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.client.delete_graph()

    def seed(self, scenario=None):
        return self.repo.seed_demo(FIXTURES, scenario)

    def assert_impacts(self, as_of_iso, expected_impacts):
        response = self.repo.list_impacts(instant_ms(as_of_iso))
        by_id = {i["commitment_id"]: i for i in response["impacts"]}
        self.assertEqual(set(by_id), {"com_acme_sso", "com_birch_audit", "com_cedar_export", "com_delta_sso"})
        for commitment_id, expected in expected_impacts.items():
            actual = summarize(by_id[commitment_id])
            for key, value in expected.items():
                self.assertEqual(actual[key], value, "%s %s at %s" % (commitment_id, key, as_of_iso))
        return response


class BaselineTests(RepositoryTestCase):
    def setUp(self):
        self.seed()

    def test_baseline_matches_expected(self):
        expected = load("expected/baseline.json")
        response = self.assert_impacts(expected["as_of"], expected["impacts"])
        self.assertEqual(response["completeness"], {"complete": True, "truncated": False, "warnings": []})
        self.assertTrue(response["evidence_version"].endswith(":0"))
        self.assertEqual(self.repo.get_version(), response["evidence_version"])

    def test_update_scenarios_match_expected(self):
        expected = load("expected/updates.json")
        for update in expected["updates"]:
            op = {"op": "apply_update", "work_item_id": update["work_item_id"],
                  "available_at": update["new_available_at"], "effective_at": expected["preview_created_at"],
                  "decision_id": "dec_test_" + update["id"], "forecast_id": "fc_test_" + update["id"],
                  "source_id": "src_dec12", "quote": "DEC-12: Approved."}
            self.seed({"operations": [op]})
            response = self.assert_impacts(expected["as_of"], update["impacts"])
            flagged = sorted(i["commitment_id"] for i in response["impacts"] if i["status"] == "date_conflict")
            self.assertEqual(flagged, update["flagged_commitment_ids"], update["id"])
            self.assertNotIn("com_cedar_export", flagged)

    def test_every_scenario_matches_expected(self):
        paths = sorted((FIXTURES / "expected" / "scenarios").glob("*.json"))
        self.assertGreaterEqual(len(paths), 15)
        for path in paths:
            scenario = json.loads(path.read_text(encoding="utf-8"))
            expected = scenario["expected"]
            if expected["import"] == "rejected":
                before = self.seed()
                with self.assertRaises(FixtureError, msg=scenario["id"]):
                    self.seed(scenario)
                self.assertEqual(self.repo.get_version().split(":")[0], before, "nothing may be written")
                continue
            self.seed(scenario)
            for query in expected["queries"]:
                self.assert_impacts(query["as_of"], query["impacts"])

    def test_evidence_is_exact_and_provenanced(self):
        self.seed({"operations": [{"op": "apply_update", "work_item_id": "wi_permissions",
                                    "available_at": "2026-10-28", "effective_at": "2026-10-17T14:30:00+05:30",
                                    "decision_id": "dec_t", "forecast_id": "fc_t", "source_id": "src_dec12",
                                    "quote": "DEC-12: Approved."}]})
        response = self.repo.list_impacts(instant_ms("2026-10-17T15:00:00+05:30"))
        flagged = [i for i in response["impacts"] if i["status"] == "date_conflict"]
        self.assertEqual(len(flagged), 2)
        for impact in response["impacts"]:
            self.assertTrue(impact["citations"])
            for citation in impact["citations"]:
                body = self.repo.get_source(citation["source_id"])["body"]
                self.assertIn(citation["quote"], body)
            for path in impact["paths"]:
                self.assertEqual([n["kind"] for n in path["nodes"][:2]], ["customer", "commitment"])
                for edge in path["edges"]:
                    self.assertTrue(edge["source_id"], edge)
        for impact in flagged:
            for blocker in impact["blockers"]:
                count = self.client.read(
                    "MATCH (d:Decision {id: $d})-[:ESTABLISHES]->(f:Forecast {id: $f}) RETURN count(*)",
                    {"d": blocker["decision_id"], "f": blocker["forecast_id"]})[0][0]
                self.assertEqual(count, 1, blocker)
        acme = next(i for i in flagged if i["commitment_id"] == "com_acme_sso")
        self.assertEqual(acme["blockers"][0]["decision_id"], "dec_t")
        self.assertEqual([e["to_id"] for e in acme["paths"][0]["edges"]],
                         ["com_acme_sso", "wi_sso", "wi_identity_migration", "wi_permissions"])

    def test_conflicting_forecast_is_not_a_confirmed_blocker(self):
        # A second active forecast past the due date makes the item conflicting, not a blocker.
        self.seed({"operations": [{"op": "add_forecast", "forecast": {
            "id": "fc_late", "work_item_id": "wi_export_worker", "available_at": "2026-10-30",
            "valid_from": "2026-10-02T10:00:00+05:30", "valid_to": None, "status": "accepted",
            "established_by_decision_id": "dec_baseline_wi_export_worker", "source_id": "src_export_plan",
            "quote": "Export worker: forecast available October 19, 2026."}}]})
        impact = self.repo.get_evidence("com_cedar_export", instant_ms("2026-10-17T10:00:00+05:30"))
        self.assertEqual(impact["status"], "needs_verification")
        self.assertEqual(impact["blockers"], [])
        self.assertIn("conflicting_forecasts", [warning_code(r) for r in impact["reasons"]])

    def test_blocker_without_establishing_decision_is_not_confirmed(self):
        self.seed({"operations": [{"op": "apply_update", "work_item_id": "wi_permissions",
                                    "available_at": "2026-10-28", "effective_at": "2026-10-17T14:30:00+05:30",
                                    "decision_id": "dec_t", "forecast_id": "fc_t", "source_id": "src_dec12",
                                    "quote": "DEC-12: Approved."}]})
        self.client.write("MATCH (:Decision)-[e:ESTABLISHES]->(:Forecast {id: 'fc_t'}) DELETE e")
        response = self.repo.list_impacts(instant_ms("2026-10-17T15:00:00+05:30"))
        by_id = {i["commitment_id"]: i for i in response["impacts"]}
        for cid in ("com_acme_sso", "com_birch_audit"):
            self.assertEqual(by_id[cid]["status"], "needs_verification")
            self.assertEqual(by_id[cid]["blockers"], [])
            self.assertIn("missing_forecast_provenance", [warning_code(r) for r in by_id[cid]["reasons"]])
        for impact in response["impacts"]:
            self.assertTrue(all(b["decision_id"] for b in impact["blockers"]))

    def test_every_open_commitment_is_returned(self):
        self.seed({"operations": [
            {"op": "remove_relationship", "type": "REQUIRES", "from_id": "com_cedar_export", "to_id": "wi_export"},
            {"op": "remove_relationship", "type": "HAS_COMMITMENT", "from_id": "cust_delta",
             "to_id": "com_delta_sso"}]})
        response = self.repo.list_impacts(instant_ms("2026-10-17T10:00:00+05:30"))
        by_id = {i["commitment_id"]: i for i in response["impacts"]}
        self.assertEqual(len(by_id), 4)
        self.assertEqual(by_id["com_cedar_export"]["status"], "needs_verification")
        self.assertEqual(by_id["com_cedar_export"]["paths"], [])
        self.assertEqual(by_id["com_delta_sso"]["customer"], {"id": "", "name": ""})
        self.assertFalse(response["completeness"]["complete"])
        self.assertTrue(any("missing_requirement" in w for w in response["completeness"]["warnings"]))

    def test_version_read_retries_and_then_gives_up(self):
        as_of = instant_ms("2026-10-17T10:00:00+05:30")
        bump = "MATCH (g:GraphState {id: 'workspace'}) SET g.revision = g.revision + 1"
        original = self.repo._impacts
        calls = []

        def bump_first(*args):
            calls.append(1)
            if len(calls) == 1:
                self.client.write(bump)  # a confirmation lands mid-read
            return original(*args)
        self.repo._impacts = bump_first
        try:
            response = self.repo.list_impacts(as_of)
            self.assertEqual(len(calls), 2)
            self.assertEqual(response["evidence_version"], self.repo.get_version())
            self.assertTrue(response["evidence_version"].endswith(":1"))

            def always_bump(*args):
                self.client.write(bump)
                return original(*args)
            self.repo._impacts = always_bump
            with self.assertRaises(InconsistentRead):
                self.repo.list_impacts(as_of)
        finally:
            self.repo._impacts = original

    def test_get_owners(self):
        owners = self.repo.get_owners("com_birch_audit", instant_ms("2026-10-17T10:00:00+05:30"))
        self.assertEqual(owners, {"engineering_owner": {"id": "person_omar", "name": "Omar Haddad"},
                                  "account_owner": {"id": "person_nisha", "name": "Nisha Rao"}, "warnings": []})

    def test_resolve_entity(self):
        sso = self.repo.resolve_entity("SSO")
        self.assertEqual([c["id"] for c in sso], ["com_acme_sso", "com_delta_sso"])
        export = self.repo.resolve_entity("export", kind="work_item")
        self.assertEqual([c["id"] for c in export], ["wi_export", "wi_export_worker"])
        self.assertEqual([c["id"] for c in self.repo.resolve_entity("permissions service")], ["wi_permissions"])
        self.assertEqual([c["id"] for c in self.repo.resolve_entity("priya")], ["person_priya"])
        self.assertEqual([c["id"] for c in self.repo.resolve_entity("DEC-12")], ["DEC-12"])
        self.assertEqual([c["id"] for c in self.repo.resolve_entity("Acme", kind="customer")], ["cust_acme"])
        self.assertEqual(self.repo.resolve_entity("no such thing"), [])

    def test_not_found(self):
        with self.assertRaises(NotFound):
            self.repo.get_source("src_missing")
        with self.assertRaises(NotFound):
            self.repo.get_evidence("com_missing", instant_ms("2026-10-17T10:00:00+05:30"))

    def test_source_matches_fixture_and_hash(self):
        import hashlib
        source = self.repo.get_source("src_owners")
        body = (FIXTURES / "sources" / "src_owners.md").read_text(encoding="utf-8")
        self.assertEqual(source["body"], body)
        self.assertEqual(source["content_hash"], hashlib.sha256(body.encode("utf-8")).hexdigest())
        self.assertIsInstance(source["source_timestamp"], int)

    def test_list_impacts_timing(self):
        as_of = instant_ms("2026-10-17T10:00:00+05:30")
        self.repo.list_impacts(as_of)  # warm up
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            self.repo.list_impacts(as_of)
            timings.append((time.perf_counter() - start) * 1000)
        print("\nlist_impacts over 20 runs: median %.1f ms, max %.1f ms" % (statistics.median(timings), max(timings)),
              file=sys.stderr)


class SafeReseedTests(RepositoryTestCase):
    """A rejected or failed reseed must leave the whole previous workspace in place."""
    FORECAST = {"id": "fc_bad", "work_item_id": "wi_permissions", "available_at": "2026-10-28",
                "valid_from": "2026-10-17T14:30:00+05:30", "valid_to": None, "status": "accepted",
                "established_by_decision_id": "DEC-12", "source_id": "src_dec12", "quote": "DEC-12: Approved."}

    def setUp(self):
        self.seed()
        self.saved = self.repo.save_action(
            {"commitment_id": "com_acme_sso", "kind": "internal_escalation", "assignee_id": "person_priya",
             "body": "Please replan.", "citations": [{"source_id": "src_dec12", "quote": "DEC-12: Approved."}],
             "based_on_decision_ids": ["DEC-12"]}, self.repo.get_version(), "keep_me")
        self.before = self.workspace()
        self.assertIn(self.saved["action_id"], [a["id"] for a in self.before["actions"]["actions"]])

    def workspace(self):
        """Every node with all its properties, every edge, the version, Actions and impacts."""
        read = self.client.read
        return {"nodes": sorted(map(repr, read("MATCH (n) RETURN labels(n)[0], properties(n)"))),
                "edges": sorted(map(repr, read("MATCH (a)-[e]->(b) RETURN a.id, type(e), properties(e), b.id"))),
                "version": self.repo.get_version(), "actions": self.repo.list_actions("com_acme_sso"),
                "impacts": self.repo.list_impacts(instant_ms("2026-10-17T15:00:00+05:30"))}

    def graphs(self):
        from falkordb import FalkorDB
        c = self.client
        return set(FalkorDB(host=c.host, port=c.port, password=c.password).list_graphs())

    def assert_untouched(self):
        self.assertEqual(self.workspace(), self.before)
        leftovers = {g for g in self.graphs() if g.startswith(self.client.graph_name + "__")}
        self.assertEqual(leftovers, set(), "staging/backup graphs must be cleaned up")

    def fixtures_with(self, edit):
        """A temporary copy of the fixtures with edit(entities_dir) applied."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(FIXTURES, tmp / "harbor")
        edit(tmp / "harbor" / "entities")
        return tmp / "harbor"

    def test_scenario_fields_that_fail_conversion(self):
        cases = {
            "unparseable date": [{"op": "add_forecast", "forecast": dict(self.FORECAST, available_at="not-a-date")}],
            "instant without offset": [{"op": "add_forecast",
                                        "forecast": dict(self.FORECAST, valid_from="2026-10-17T14:30:00")}],
            "missing field": [{"op": "add_work_item", "work_item": {"id": "wi_no_kind", "name": "No kind"}}],
            "int date": [{"op": "add_forecast", "forecast": dict(self.FORECAST, available_at=20261028)}],
            "object status": [{"op": "add_forecast", "forecast": dict(self.FORECAST, status={"x": 1})}],
            "unknown work item kind": [{"op": "add_work_item",
                                        "work_item": {"id": "wi_odd", "name": "Odd", "kind": "epic"}}],
            "unknown relationship type": [{"op": "add_relationship", "relationship": {
                "type": "BLOCKS", "from_id": "wi_sso", "to_id": "wi_permissions",
                "source_id": "src_dec12", "quote": "DEC-12: Approved."}}],
            "malformed operation": [{"op": "remove_owner"}],
        }
        for name, operations in cases.items():
            with self.subTest(name):
                with self.assertRaises(FixtureError):
                    self.seed({"operations": operations})
                self.assert_untouched()

    def test_fixture_values_the_database_cannot_store(self):
        """The re-review reproductions: object-valued Person.name and Customer.synthetic_contract_value."""
        def set_field(file, index, field, value):
            def edit(entities):
                path = entities / file
                rows = json.loads(path.read_text(encoding="utf-8"))
                rows[index][field] = value
                path.write_text(json.dumps(rows), encoding="utf-8")
            return edit
        cases = {
            "object Person.name": set_field("people.json", 0, "name", {"unexpected": "object"}),
            "object contract value": set_field("customers.json", 0, "synthetic_contract_value", {"unexpected": 1}),
            "list Team.name": set_field("teams.json", 0, "name", ["a", "b"]),
            "bool contract value": set_field("customers.json", 0, "synthetic_contract_value", True),
            "null Person.name": set_field("people.json", 0, "name", None),
            "number Person.name": set_field("people.json", 0, "name", 42),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                with self.assertRaises(FixtureError):
                    self.repo.seed_demo(self.fixtures_with(edit))
                self.assert_untouched()

    def test_database_rejection_during_load_keeps_the_live_graph(self):
        """A write error only the database detects happens in staging, never on the live graph."""
        original = GraphClient.write

        def reject_people_in_staging(client, cypher, params=None):
            if "__staging_" in client.graph_name and ":Person)" in cypher:
                raise GraphError("graph query failed: simulated property-type rejection")
            return original(client, cypher, params)
        with mock.patch.object(GraphClient, "write", reject_people_in_staging):
            with self.assertRaises(GraphError):
                self.seed()
        self.assert_untouched()

    def test_failed_rename_keeps_the_live_graph(self):
        def rename_fails(client, graph_name):
            raise GraphError("graph query failed: simulated rename failure")
        with mock.patch.object(GraphClient, "move_to", rename_fails):
            with self.assertRaises(GraphError):
                self.seed()
        self.assert_untouched()

    def test_cleanup_failure_does_not_hide_the_load_error(self):
        write, delete = GraphClient.write, GraphClient.delete_graph

        def reject_people_in_staging(client, cypher, params=None):
            if "__staging_" in client.graph_name and ":Person)" in cypher:
                raise GraphError("graph query failed: simulated property-type rejection")
            return write(client, cypher, params)

        def staging_cleanup_fails(client):
            # Only the cleanup after the failed load: the staging graph exists by then.
            if "__staging_" in client.graph_name and client.graph_name in self.graphs():
                self.addCleanup(delete, client)  # the leftover staging graph this test causes
                raise GraphUnavailable("simulated cleanup failure")
            return delete(client)
        with mock.patch.object(GraphClient, "write", reject_people_in_staging), \
                mock.patch.object(GraphClient, "delete_graph", staging_cleanup_fails):
            with self.assertRaises(GraphError) as caught:
                self.seed()
        self.assertIn("simulated property-type rejection", str(caught.exception))
        self.assertEqual(self.workspace(), self.before)

    def test_successful_reseed_replaces_everything_and_cleans_up(self):
        dataset_id = self.seed()
        self.assertEqual(self.repo.get_version(), "%s:0" % dataset_id)
        self.assertEqual(self.repo.list_actions("com_acme_sso")["actions"], [])
        self.assertEqual({g for g in self.graphs() if g.startswith(self.client.graph_name + "__")}, set())
        indexed = {row[0] for row in self.client.read("CALL db.indexes() YIELD label RETURN label")}
        self.assertTrue({"WorkItem", "GraphState", "Action", "RequestRecord"} <= indexed, indexed)


class SeedTests(RepositoryTestCase):
    def test_unseeded_graph_raises_not_found(self):
        self.client.delete_graph()
        with self.assertRaises(NotFound):
            self.repo.get_version()

    def test_seed_replaces_dataset(self):
        first = self.seed()
        second = self.seed()
        self.assertNotEqual(first, second)
        self.assertEqual(self.repo.get_version(), second + ":0")

    def test_apply_scenario_is_pure(self):
        data = load_fixtures(FIXTURES)
        scenario = {"operations": [{"op": "remove_owner", "work_item_id": "wi_sso"}]}
        changed = apply_scenario(data, scenario)
        self.assertEqual(len(changed["relationships"]), len(data["relationships"]) - 1)


if __name__ == "__main__":
    unittest.main()
