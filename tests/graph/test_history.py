"""get_history tests against a real FalkorDB (skipped when it is unreachable).

Same setup as test_repository.py; run with the venv that has the falkordb client:
  ~/.venvs/ripple-graph/bin/python -m unittest discover -s tests/graph -t .
"""
import json
import unittest

from tests.graph.test_repository import (FIXTURES, SKIP_REASON, RepositoryTestCase, instant_ms, load,
                                         NotFound, InconsistentRead)
if SKIP_REASON is None:
    from backend.app.graph.timeutil import to_ms

WORK_ITEMS = ["wi_permissions", "wi_identity_migration", "wi_sso", "wi_audit", "wi_export", "wi_export_worker"]
OCT28 = {"op": "apply_update", "work_item_id": "wi_permissions", "available_at": "2026-10-28",
         "effective_at": "2026-10-17T14:30:00+05:30", "decision_id": "dec_t", "forecast_id": "fc_t",
         "source_id": "src_dec12", "quote": "DEC-12: Approved."}


def fixture_scenario(name):
    return json.loads((FIXTURES / "expected" / "scenarios" / (name + ".json")).read_text(encoding="utf-8"))


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class HistoryTests(RepositoryTestCase):
    def assert_citations_exact(self, history):
        for forecast in history["forecasts"]:
            self.assertGreaterEqual(len(forecast["citations"]), 1, forecast["id"])
            for citation in forecast["citations"]:
                self.assertIn(citation["quote"], self.repo.get_source(citation["source_id"])["body"])

    def test_baseline_history_for_each_work_item(self):
        self.seed()
        fixture_forecasts = {f["work_item_id"]: f for f in load("decisions/forecasts.json")}
        decisions = {d["id"]: d for d in load("decisions/decisions.json")}
        for wi_id in WORK_ITEMS:
            history = self.repo.get_history(wi_id)
            self.assertEqual(history["evidence_version"], self.repo.get_version())
            (forecast,) = history["forecasts"]
            expected = fixture_forecasts[wi_id]
            decision = decisions[expected["established_by_decision_id"]]
            self.assertEqual(forecast["id"], expected["id"])
            self.assertEqual(forecast["available_at"], to_ms(expected["available_at"]))
            self.assertEqual(forecast["valid_from"], instant_ms(expected["valid_from"]))
            self.assertIsNone(forecast["valid_to"])
            self.assertEqual(forecast["decision_id"], decision["id"])
            self.assertIsNone(forecast["supersedes_id"])
            self.assertEqual(forecast["decision_summary"], decision["summary"])
            wanted = []  # forecast quote, then decision quote; identical pairs collapse to one
            for pair in ((expected["source_id"], expected["quote"]), (decision["source_id"], decision["quote"])):
                if {"source_id": pair[0], "quote": pair[1]} not in wanted:
                    wanted.append({"source_id": pair[0], "quote": pair[1]})
            self.assertEqual(forecast["citations"], wanted)
            self.assert_citations_exact(history)
        self.assertEqual(self.repo.get_history("wi_permissions")["forecasts"][0]["decision_id"], "DEC-12")

    def test_canonical_update_adds_superseding_forecast(self):
        self.seed({"operations": [OCT28]})
        history = self.repo.get_history("wi_permissions")
        old, new = history["forecasts"]
        self.assertEqual(old["id"], "fc_wi_permissions_baseline")
        self.assertEqual(old["decision_id"], "DEC-12")
        self.assertEqual(new["id"], "fc_t")
        self.assertEqual(new["decision_id"], "dec_t")
        self.assertEqual(new["supersedes_id"], "DEC-12")
        self.assertEqual(new["decision_summary"], "scenario update")
        self.assertEqual(old["valid_to"], new["valid_from"])
        self.assertEqual(new["valid_from"], instant_ms("2026-10-17T14:30:00+05:30"))
        self.assertIsNone(new["valid_to"])
        self.assertEqual(new["available_at"], to_ms("2026-10-28"))
        self.assertLess(old["valid_from"], new["valid_from"])
        self.assert_citations_exact(history)
        # Other work items are untouched, and DEC-12 is not inferred for the new forecast.
        self.assertEqual(len(self.repo.get_history("wi_identity_migration")["forecasts"]), 1)

    def test_history_boundary_scenario(self):
        scenario = fixture_scenario("scn_history_update_boundary")
        self.seed(scenario)
        old, new = self.repo.get_history("wi_permissions")["forecasts"]
        op = scenario["operations"][0]
        self.assertEqual((old["id"], old["decision_id"]), ("fc_wi_permissions_baseline", "DEC-12"))
        self.assertEqual((new["id"], new["decision_id"]), (op["forecast_id"], op["decision_id"]))
        self.assertEqual(new["supersedes_id"], "DEC-12")
        self.assertEqual(old["valid_to"], new["valid_from"], instant_ms(op["effective_at"]))
        self.assertEqual(new["citations"][0], {"source_id": op["source_id"], "quote": op["quote"]})
        self.assert_citations_exact(self.repo.get_history("wi_permissions"))

    def test_history_past_interval_scenario(self):
        scenario = fixture_scenario("scn_history_past_interval")
        self.seed(scenario)
        history = self.repo.get_history("wi_permissions")
        early, baseline = history["forecasts"]  # ordered by valid_from ascending
        self.assertEqual(early["id"], "fc_scn_early_permissions")
        self.assertEqual(early["decision_id"], "dec_scn_early_permissions")
        self.assertEqual(early["available_at"], to_ms("2026-10-25"))
        self.assertEqual(early["valid_to"], instant_ms("2026-10-01T10:00:00+05:30"))
        self.assertEqual(early["valid_to"], baseline["valid_from"])
        self.assertEqual(baseline["decision_id"], "DEC-12")
        self.assertIsNone(baseline["valid_to"])
        self.assert_citations_exact(history)

    def test_non_accepted_forecasts_are_excluded(self):
        self.seed({"operations": [{"op": "add_forecast", "forecast": {
            "id": "fc_proposed", "work_item_id": "wi_sso", "available_at": "2026-11-30",
            "valid_from": "2026-10-02T10:00:00+05:30", "valid_to": None, "status": "proposed",
            "established_by_decision_id": "dec_baseline_wi_sso", "source_id": "src_sso_plan",
            "quote": "SSO feature: forecast available October 23, 2026."}}]})
        self.assertEqual([f["id"] for f in self.repo.get_history("wi_sso")["forecasts"]], ["fc_wi_sso_baseline"])

    def test_work_item_without_forecast_has_empty_history(self):
        self.seed({"operations": [{"op": "add_work_item", "work_item": {
            "id": "wi_new", "name": "New thing", "kind": "feature"}}]})
        self.assertEqual(self.repo.get_history("wi_new")["forecasts"], [])

    def test_not_found(self):
        self.seed()
        with self.assertRaises(NotFound):
            self.repo.get_history("wi_missing")
        with self.assertRaises(NotFound):
            self.repo.get_history("com_acme_sso")  # exists, but is not a work item

    def test_history_version_read_retries_and_then_gives_up(self):
        self.seed()
        bump = "MATCH (g:GraphState {id: 'workspace'}) SET g.revision = g.revision + 1"
        original = self.repo._history
        calls = []

        def bump_first(*args):
            calls.append(1)
            if len(calls) == 1:
                self.client.write(bump)
            return original(*args)
        self.repo._history = bump_first
        try:
            history = self.repo.get_history("wi_sso")
            self.assertEqual(len(calls), 2)
            self.assertEqual(history["evidence_version"], self.repo.get_version())

            def always_bump(*args):
                self.client.write(bump)
                return original(*args)
            self.repo._history = always_bump
            with self.assertRaises(InconsistentRead):
                self.repo.get_history("wi_sso")
        finally:
            self.repo._history = original


if __name__ == "__main__":
    unittest.main()
