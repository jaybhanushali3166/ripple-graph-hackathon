"""Decision codes, who-knows-what, the graph view and the demo dependency toggle, against a
real FalkorDB (skipped when unreachable). Every class gets its own randomly named graph."""
import unittest

from tests.graph.test_writes import (AS_OF, PREVIEW_AT, MINUTE, SKIP_REASON, WriteTestCase,
                                     make_proposal, make_source)

if not SKIP_REASON:
    from backend.app.graph.errors import ReviewRequired, StaleEvidence

DEPENDENCY = ("wi_identity_migration", "wi_permissions", "src_identity_plan",
              "The identity migration project depends on the permissions service.")


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class DecisionCodeTests(WriteTestCase):
    def test_confirmed_decisions_get_the_next_dec_code(self):
        first = self.confirm()
        self.assertEqual(first["decision_id"], "DEC-13")
        later = PREVIEW_AT + 5 * MINUTE
        second = self.confirm(key="k2", proposal=make_proposal("2026-11-10", effective_at=later),
                              source=make_source("src_note_nov10"), version=first["evidence_version"],
                              now_ms=later + MINUTE)
        self.assertEqual(second["decision_id"], "DEC-14")
        history = self.repo.get_history("wi_permissions")["forecasts"]
        self.assertEqual([(f["decision_id"], f["supersedes_id"]) for f in history],
                         [("DEC-12", None), ("DEC-13", "DEC-12"), ("DEC-14", "DEC-13")])


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class ExpertsTests(WriteTestCase):
    def test_owner_ranks_first_and_every_reason_is_quoted(self):
        result = self.repo.get_experts("wi_permissions")
        self.assertEqual([e["id"] for e in result["experts"]], ["person_priya", "person_lena"])
        priya = result["experts"][0]
        self.assertEqual(sorted({r["kind"] for r in priya["reasons"]}), ["discussed", "member_of", "owns"])
        for expert in result["experts"]:
            for reason in expert["reasons"]:
                body = self.repo.get_source(reason["source_id"])["body"]
                self.assertIn(reason["quote"], body)

    def test_unknown_work_item_is_not_found(self):
        from backend.app.graph.errors import NotFound
        with self.assertRaises(NotFound):
            self.repo.get_experts("wi_nope")


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class GraphViewTests(WriteTestCase):
    def flagged(self):
        return sorted(i["commitment_id"] for i in self.repo.list_impacts(AS_OF)["impacts"]
                      if i["status"] == "date_conflict")

    def test_graph_has_the_dependency_edges(self):
        graph = self.repo.get_graph()
        kinds = {n["kind"] for n in graph["nodes"]}
        self.assertTrue({"customer", "commitment", "feature", "component"} <= kinds)
        self.assertIn(("wi_identity_migration", "wi_permissions", "DEPENDS_ON"),
                      {(e["from_id"], e["to_id"], e["relation"]) for e in graph["edges"]})

    def test_removing_the_dependency_clears_the_flag_and_restoring_brings_it_back(self):
        confirmed = self.confirm()
        self.assertEqual(self.flagged(), ["com_acme_sso", "com_birch_audit"])
        source_from, source_to, source_id, quote = DEPENDENCY
        removed = self.repo.set_dependency(source_from, source_to, False, source_id, quote,
                                           confirmed["evidence_version"])
        self.assertEqual(self.flagged(), ["com_birch_audit"])
        restored = self.repo.set_dependency(source_from, source_to, True, source_id, quote, removed)
        self.assertEqual(self.flagged(), ["com_acme_sso", "com_birch_audit"])
        self.assertEqual(self.repo.get_version(), restored)

    def test_stale_or_repeated_toggles_change_nothing(self):
        version = self.repo.get_version()
        removed = self.repo.set_dependency(*DEPENDENCY[:2], False, *DEPENDENCY[2:], version)
        with self.assertRaises(StaleEvidence):
            self.repo.set_dependency(*DEPENDENCY[:2], True, *DEPENDENCY[2:], version)
        with self.assertRaises(ReviewRequired):
            self.repo.set_dependency(*DEPENDENCY[:2], False, *DEPENDENCY[2:], removed)
        self.assertEqual(self.repo.get_version(), removed)


if __name__ == "__main__":
    unittest.main()
