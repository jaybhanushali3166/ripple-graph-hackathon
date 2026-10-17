"""Integrity tests for the synthetic Harbor fixtures in fixtures/harbor (no database).

Fixture format
--------------
Layout (all JSON is UTF-8; entity files are JSON lists):
  entities/   customers, commitments, work_items, people, teams, relationships, aliases
  decisions/  decisions.json, forecasts.json (the seeded baseline)
  sources/    index.json plus one <source_id>.md body per source
  expected/   baseline.json, updates.json, history.json, and scenarios/*.json overlays

Dates: a date-only value "YYYY-MM-DD" means the end of that day in Asia/Kolkata
(next IST midnight minus 1 ms). Instants are ISO 8601 with "+05:30". Fixtures never
contain epoch numbers; code converts (see eod_ms/instant_ms below).

Provenance: every relationship {type, from_id, to_id, source_id, quote} and every
commitment, decision and forecast carries source_id and a quote that is an exact
substring of that source's body. content_hash is computed by code, not stored.
Forecast intervals are half-open: valid_from <= as_of < valid_to (valid_to null = open).
Each Forecast names exactly one establishing Decision (established_by_decision_id).

aliases.json: {alias, kind, candidate_ids, ambiguous}; ambiguous means more than one candidate.

Expected files: per-commitment {customer_id, status, blocker_work_item_ids,
engineering_owner_id, account_owner_id, warnings}. Warning codes are fixture-level
labels: missing_forecast, conflicting_forecasts, missing_engineering_owner,
ambiguous_engineering_owner, depth_limit_exceeded, missing_requirement, missing_customer.
A scenario may add truncated: true. Conflicting forecasts (several active accepted forecasts
for one work item) are never a confirmed blocker, even if one of them is past due.
expected/history.json uses <placeholders> for server-generated IDs and the preview time.

Scenario overlays (expected/scenarios/*.json): {id, description, base, added_sources?,
operations, expected}. The operation vocabulary:
  remove_relationship {type, from_id, to_id}
  add_relationship    {relationship}
  remove_forecast     {forecast_id}
  add_forecast        {forecast}
  add_decision        {decision}
  add_work_item       {work_item}
  remove_owner        {work_item_id}          removes every OWNS edge to it
  apply_update        {work_item_id, available_at, effective_at, decision_id,
                       forecast_id, source_id, quote}
                      closes the open forecast at effective_at, adds an accepted
                      forecast and approved Decision that supersedes the closed
                      forecast's establishing Decision
expected is {import: "accepted", queries: [{as_of, impacts}]} or
{import: "rejected", reason: "dependency_cycle"}.

The reference walk below only checks that the fixtures are consistent with the story
and the contract rules (strict available_at > due_at, four-hop bound). The real answer
comes from FalkorDB later.

Run from the repo root: python3 -m unittest discover -s tests/graph -t .
"""
import copy
import hashlib
import json
import re
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "harbor"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_HOPS = 4
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")
REQUIRED_SOURCES = {
    "src_acme_handoff", "src_birch_handoff", "src_cedar_handoff", "src_delta_handoff",
    "src_sso_plan", "src_identity_plan", "src_audit_plan", "src_export_plan",
    "src_permissions_ticket", "src_owners", "src_dec12"}
# relationship type -> (from kind, to kind)
REL_KINDS = {
    "HAS_COMMITMENT": ("customer", "commitment"), "REQUIRES": ("commitment", "work_item"),
    "DEPENDS_ON": ("work_item", "work_item"), "OWNS": ("person", "work_item"),
    "ACCOUNT_OWNER": ("person", "customer"), "MEMBER_OF": ("person", "team"),
    "RESPONSIBLE_FOR": ("team", "work_item")}
LIVE_UPDATE_TIME = "2026-10-17T14:30:00+05:30"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def eod_ms(day):
    next_midnight = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(0), tzinfo=IST)
    return round(next_midnight.timestamp() * 1000) - 1


def instant_ms(iso):
    return round(datetime.fromisoformat(iso).timestamp() * 1000)


def to_ms(value):
    return eod_ms(value) if DATE_RE.match(value) else instant_ms(value)


class Dataset:
    """In-memory copy of the seed that scenario operations can modify."""

    def __init__(self):
        self.customers = load("entities/customers.json")
        self.commitments = load("entities/commitments.json")
        self.work_items = load("entities/work_items.json")
        self.people = load("entities/people.json")
        self.teams = load("entities/teams.json")
        self.relationships = load("entities/relationships.json")
        self.decisions = load("decisions/decisions.json")
        self.forecasts = load("decisions/forecasts.json")
        self.sources = {s["id"]: (ROOT / "sources" / s["file"]).read_text(encoding="utf-8")
                        for s in load("sources/index.json")}

    def ids(self):
        return {"customer": {c["id"] for c in self.customers},
                "commitment": {c["id"] for c in self.commitments},
                "work_item": {w["id"] for w in self.work_items},
                "person": {p["id"] for p in self.people},
                "team": {t["id"] for t in self.teams},
                "decision": {d["id"] for d in self.decisions},
                "forecast": {f["id"] for f in self.forecasts}}

    def edges(self, rel_type, from_id=None, to_id=None):
        return [r for r in self.relationships if r["type"] == rel_type
                and from_id in (None, r["from_id"]) and to_id in (None, r["to_id"])]

    # ---- scenario operations
    def apply(self, op):
        kind = op["op"]
        if kind == "remove_relationship":
            hit = self.edges(op["type"], op["from_id"], op["to_id"])
            assert len(hit) == 1, op
            self.relationships.remove(hit[0])
        elif kind == "add_relationship":
            self.relationships.append(op["relationship"])
        elif kind == "remove_forecast":
            hit = [f for f in self.forecasts if f["id"] == op["forecast_id"]]
            assert len(hit) == 1, op
            self.forecasts.remove(hit[0])
        elif kind == "add_forecast":
            self.forecasts.append(op["forecast"])
        elif kind == "add_decision":
            self.decisions.append(op["decision"])
        elif kind == "add_work_item":
            self.work_items.append(op["work_item"])
        elif kind == "remove_owner":
            hit = self.edges("OWNS", to_id=op["work_item_id"])
            assert hit, op
            for r in hit:
                self.relationships.remove(r)
        elif kind == "apply_update":
            self.apply_update(op)
        else:
            raise AssertionError("unknown operation %r" % kind)

    def apply_update(self, op):
        effective = instant_ms(op["effective_at"])
        open_forecasts = [f for f in self.forecasts if f["work_item_id"] == op["work_item_id"]
                          and f["status"] == "accepted" and f["valid_to"] is None]
        assert len(open_forecasts) == 1, op
        old = open_forecasts[0]
        assert instant_ms(old["valid_from"]) < effective, op
        old["valid_to"] = op["effective_at"]
        self.decisions.append({
            "id": op["decision_id"], "summary": "scenario update", "decided_at": op["effective_at"],
            "status": "approved", "revises_work_item_id": op["work_item_id"],
            "supersedes_id": old["established_by_decision_id"], "source_id": op["source_id"],
            "quote": op["quote"]})
        self.forecasts.append({
            "id": op["forecast_id"], "work_item_id": op["work_item_id"], "available_at": op["available_at"],
            "valid_from": op["effective_at"], "valid_to": None, "status": "accepted",
            "established_by_decision_id": op["decision_id"], "source_id": op["source_id"],
            "quote": op["quote"]})


def scenario_dataset(scenario):
    ds = Dataset()
    for s in scenario.get("added_sources", []):
        ds.sources[s["id"]] = s["body"]
    for op in scenario["operations"]:
        ds.apply(op)
    return ds


# ---- dataset checks shared by the seed and every scenario overlay
def reference_errors(ds):
    ids, errors = ds.ids(), []
    for r in ds.relationships:
        from_kind, to_kind = REL_KINDS[r["type"]]
        if r["from_id"] not in ids[from_kind]:
            errors.append("unknown from_id in %r" % r)
        if r["to_id"] not in ids[to_kind]:
            errors.append("unknown to_id in %r" % r)
    for d in ds.decisions:
        if d["revises_work_item_id"] not in ids["work_item"]:
            errors.append("decision %s revises unknown work item" % d["id"])
        if d["supersedes_id"] is not None and d["supersedes_id"] not in ids["decision"]:
            errors.append("decision %s supersedes unknown decision" % d["id"])
    for f in ds.forecasts:
        if f["work_item_id"] not in ids["work_item"]:
            errors.append("forecast %s unknown work item" % f["id"])
        if f["established_by_decision_id"] not in ids["decision"]:
            errors.append("forecast %s unknown decision" % f["id"])
    return errors


def quote_errors(ds):
    records = (ds.relationships + ds.commitments + ds.decisions + ds.forecasts)
    errors = []
    for rec in records:
        body = ds.sources.get(rec.get("source_id"))
        if body is None:
            errors.append("unknown source in %r" % rec)
        elif not rec.get("quote") or rec["quote"] not in body:
            errors.append("quote not an exact substring in %r" % rec)
    return errors


def find_cycle(ds):
    graph = {}
    for r in ds.edges("DEPENDS_ON"):
        graph.setdefault(r["from_id"], []).append(r["to_id"])
    state = {}

    def visit(node):
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1 or (nxt not in state and visit(nxt)):
                return True
        state[node] = 2
        return False
    return any(n not in state and visit(n) for n in list(graph))


def longest_chain(ds, start):
    deps = [r["to_id"] for r in ds.edges("DEPENDS_ON", from_id=start)]
    return 0 if not deps else 1 + max(longest_chain(ds, d) for d in deps)


def impact(ds, commitment_id, as_of_iso):
    """Reference implementation of the contract rules over the in-memory fixtures."""
    as_of = instant_ms(as_of_iso)
    commitment = next(c for c in ds.commitments if c["id"] == commitment_id)
    due = to_ms(commitment["due_at"])
    customers = ds.edges("HAS_COMMITMENT", to_id=commitment_id)
    customer = customers[0]["from_id"] if customers else None
    roots = sorted(r["to_id"] for r in ds.edges("REQUIRES", from_id=commitment_id))
    warnings, visited = set(), set()
    if customer is None:
        warnings.add("missing_customer")
    if not roots:
        warnings.add("missing_requirement")

    def walk(work_item, depth):
        visited.add(work_item)
        deps = [r["to_id"] for r in ds.edges("DEPENDS_ON", from_id=work_item)]
        if deps and depth == MAX_HOPS:
            warnings.add("depth_limit_exceeded")
            return
        for dep in deps:
            walk(dep, depth + 1)
    for root in roots:
        walk(root, 0)

    blockers = set()
    for wi in visited:
        active = [f for f in ds.forecasts if f["work_item_id"] == wi and f["status"] == "accepted"
                  and instant_ms(f["valid_from"]) <= as_of
                  and (f["valid_to"] is None or as_of < instant_ms(f["valid_to"]))]
        if not active:
            warnings.add("missing_forecast")
        elif len({to_ms(f["available_at"]) for f in active}) > 1:
            warnings.add("conflicting_forecasts")
        elif to_ms(active[0]["available_at"]) > due:  # strict: same day is not a conflict
            blockers.add(wi)

    subjects = sorted(blockers) or roots
    owner_sets = [{r["from_id"] for r in ds.edges("OWNS", to_id=w)} for w in subjects]
    engineering_owner = None
    if not subjects:
        pass  # missing_requirement already explains this
    elif any(not s for s in owner_sets):
        warnings.add("missing_engineering_owner")
    elif len(set().union(*owner_sets)) > 1:
        warnings.add("ambiguous_engineering_owner")
    else:
        engineering_owner = next(iter(owner_sets[0]))
    account = [r["from_id"] for r in ds.edges("ACCOUNT_OWNER", to_id=customer)] if customer else []
    if customer and len(account) != 1:
        warnings.add("missing_account_owner")

    status = "date_conflict" if blockers else ("needs_verification" if warnings else "no_detected_conflict")
    return {"customer_id": customer, "status": status, "blocker_work_item_ids": sorted(blockers),
            "engineering_owner_id": engineering_owner,
            "account_owner_id": account[0] if len(account) == 1 else None,
            "warnings": sorted(warnings), "truncated": "depth_limit_exceeded" in warnings}


class FixtureCase(unittest.TestCase):
    def assert_impacts(self, ds, as_of, expected_impacts):
        for commitment_id, expected in expected_impacts.items():
            actual = impact(ds, commitment_id, as_of)
            for key, value in expected.items():
                self.assertEqual(actual[key], value, "%s %s at %s" % (commitment_id, key, as_of))


class FixtureIntegrityTests(FixtureCase):
    def setUp(self):
        self.ds = Dataset()

    def test_all_json_parses(self):
        files = sorted(ROOT.rglob("*.json"))
        self.assertGreaterEqual(len(files), 20)
        for path in files:
            json.loads(path.read_text(encoding="utf-8"))

    def test_ids_are_unique_per_type(self):
        collections = {"customer": self.ds.customers, "commitment": self.ds.commitments,
                       "work_item": self.ds.work_items, "person": self.ds.people, "team": self.ds.teams,
                       "decision": self.ds.decisions, "forecast": self.ds.forecasts}
        for name, items in collections.items():
            ids = [i["id"] for i in items]
            self.assertEqual(len(ids), len(set(ids)), name)
        index_ids = [s["id"] for s in load("sources/index.json")]
        self.assertEqual(len(index_ids), len(set(index_ids)))

    def test_canonical_story_ids(self):
        ids = self.ds.ids()
        self.assertEqual(ids["customer"], {"cust_acme", "cust_birch", "cust_cedar", "cust_delta"})
        self.assertEqual(ids["commitment"], {"com_acme_sso", "com_birch_audit", "com_cedar_export", "com_delta_sso"})
        self.assertEqual(ids["work_item"], {"wi_sso", "wi_identity_migration", "wi_permissions",
                                            "wi_audit", "wi_export", "wi_export_worker"})
        self.assertGreaterEqual(len(ids["team"]), 2)
        for c in self.ds.commitments:
            self.assertEqual(c["status"], "open")
        for c in self.ds.customers:
            self.assertIn("synthetic_contract_value", c)

    def test_canonical_relationships(self):
        def pairs(t):
            return {(r["from_id"], r["to_id"]) for r in self.ds.edges(t)}
        self.assertEqual(pairs("REQUIRES"), {("com_acme_sso", "wi_sso"), ("com_delta_sso", "wi_sso"),
                                              ("com_birch_audit", "wi_audit"), ("com_cedar_export", "wi_export")})
        self.assertEqual(pairs("DEPENDS_ON"), {("wi_sso", "wi_identity_migration"),
                                                ("wi_identity_migration", "wi_permissions"),
                                                ("wi_audit", "wi_permissions"), ("wi_export", "wi_export_worker")})
        self.assertEqual(pairs("OWNS"), {("person_priya", "wi_permissions"), ("person_lena", "wi_sso"),
                                          ("person_lena", "wi_identity_migration"), ("person_omar", "wi_audit"),
                                          ("person_eli", "wi_export"), ("person_eli", "wi_export_worker")})
        self.assertEqual(pairs("ACCOUNT_OWNER"), {("person_maya", "cust_acme"), ("person_nisha", "cust_birch"),
                                                   ("person_leo", "cust_cedar"), ("person_noah", "cust_delta")})
        self.assertEqual(pairs("HAS_COMMITMENT"), {("cust_acme", "com_acme_sso"), ("cust_birch", "com_birch_audit"),
                                                    ("cust_cedar", "com_cedar_export"), ("cust_delta", "com_delta_sso")})
        self.assertTrue(pairs("MEMBER_OF"))
        self.assertTrue(pairs("RESPONSIBLE_FOR"))

    def test_all_references_exist(self):
        self.assertEqual(reference_errors(self.ds), [])

    def test_aliases_resolve(self):
        ids = self.ds.ids()
        aliases = load("entities/aliases.json")
        by_alias = {a["alias"]: a for a in aliases}
        for a in aliases:
            self.assertTrue(a["candidate_ids"])
            self.assertEqual(a["ambiguous"], len(a["candidate_ids"]) > 1, a["alias"])
            for cid in a["candidate_ids"]:
                self.assertIn(cid, ids[a["kind"]], a["alias"])
        self.assertEqual(by_alias["permissions service"]["candidate_ids"], ["wi_permissions"])
        self.assertEqual(by_alias["Priya"]["candidate_ids"], ["person_priya"])
        self.assertEqual(by_alias["DEC-12"]["candidate_ids"], ["DEC-12"])
        self.assertEqual(by_alias["Acme"]["candidate_ids"], ["cust_acme"])
        self.assertTrue(any(a["ambiguous"] for a in aliases))

    def test_source_index_matches_files_both_ways(self):
        index = load("sources/index.json")
        indexed = {s["file"] for s in index}
        on_disk = {p.name for p in (ROOT / "sources").glob("*.md")}
        self.assertEqual(indexed, on_disk)
        self.assertTrue(REQUIRED_SOURCES <= {s["id"] for s in index})
        for s in index:
            self.assertEqual(s["file"], s["id"] + ".md")
            self.assertIn(s["type"], {"ticket", "chat", "doc", "handoff", "meeting_notes"})
            self.assertTrue(s["title"])
            self.assertRegex(s["source_timestamp"], INSTANT_RE)

    def test_source_bodies_are_short_and_distinct(self):
        digests = set()
        for source_id, body in self.ds.sources.items():
            self.assertTrue(5 <= len(body.strip().splitlines()) <= 25, source_id)
            digests.add(hashlib.sha256(body.encode("utf-8")).hexdigest())
        self.assertEqual(len(digests), len(self.ds.sources))

    def test_every_quote_is_an_exact_substring(self):
        self.assertEqual(quote_errors(self.ds), [])

    def test_every_proof_bearing_relationship_has_source_and_quote(self):
        self.assertEqual({r["type"] for r in self.ds.relationships}, set(REL_KINDS))
        for r in self.ds.relationships:
            self.assertTrue(r["source_id"] and r["quote"], r)

    def test_date_fields_use_documented_formats(self):
        for c in self.ds.commitments:
            self.assertRegex(c["due_at"], DATE_RE)
        for f in self.ds.forecasts:
            self.assertRegex(f["available_at"], DATE_RE)
            self.assertRegex(f["valid_from"], INSTANT_RE)
            if f["valid_to"] is not None:
                self.assertRegex(f["valid_to"], INSTANT_RE)
        for d in self.ds.decisions:
            self.assertRegex(d["decided_at"], INSTANT_RE)
            self.assertEqual(d["status"], "approved")

    def test_end_of_day_helper(self):
        # 2026-10-23 23:59:59.999 IST == 18:29:59.999 UTC
        expected = round(datetime(2026, 10, 23, 18, 29, 59, tzinfo=timezone.utc).timestamp() * 1000) + 999
        self.assertEqual(eod_ms("2026-10-23"), expected)

    def test_each_work_item_has_one_baseline_forecast_with_decision(self):
        decisions = {d["id"]: d for d in self.ds.decisions}
        for wi in self.ds.work_items:
            forecasts = [f for f in self.ds.forecasts if f["work_item_id"] == wi["id"]]
            self.assertEqual(len(forecasts), 1, wi["id"])
            f = forecasts[0]
            self.assertEqual((f["status"], f["valid_from"], f["valid_to"]),
                             ("accepted", "2026-10-01T10:00:00+05:30", None))
            self.assertLess(instant_ms(f["valid_from"]), instant_ms("2026-10-17T00:00:00+05:30"))
            decision = decisions[f["established_by_decision_id"]]
            self.assertEqual(decision["revises_work_item_id"], wi["id"])
            expected_id = "DEC-12" if wi["id"] == "wi_permissions" else "dec_baseline_" + wi["id"]
            self.assertEqual(decision["id"], expected_id)
        permissions = next(f for f in self.ds.forecasts if f["work_item_id"] == "wi_permissions")
        self.assertEqual(permissions["available_at"], "2026-10-21")

    def test_each_decision_establishes_at_most_its_own_work_items(self):
        # a Forecast has exactly one establishing decision by construction; each baseline
        # decision is used by exactly one forecast
        used = [f["established_by_decision_id"] for f in self.ds.forecasts]
        self.assertEqual(len(used), len(set(used)))

    def test_baseline_date_constraints(self):
        limits = {"wi_sso": "2026-10-23", "wi_identity_migration": "2026-10-23", "wi_audit": "2026-10-26",
                  "wi_export": "2026-10-23", "wi_export_worker": "2026-10-23"}
        for f in self.ds.forecasts:
            if f["work_item_id"] in limits:
                self.assertLessEqual(eod_ms(f["available_at"]), eod_ms(limits[f["work_item_id"]]), f["id"])

    def test_depends_on_graph_is_acyclic_and_within_four_hops(self):
        self.assertFalse(find_cycle(self.ds))
        for wi in self.ds.work_items:
            self.assertLessEqual(longest_chain(self.ds, wi["id"]), MAX_HOPS)


class ReferenceWalkTests(FixtureCase):
    def test_expected_baseline_matches_reference_walk(self):
        expected = load("expected/baseline.json")
        self.assertEqual(set(expected["impacts"]), {"com_acme_sso", "com_birch_audit", "com_cedar_export", "com_delta_sso"})
        for entry in expected["impacts"].values():
            self.assertEqual(entry["status"], "no_detected_conflict")
        self.assert_impacts(Dataset(), expected["as_of"], expected["impacts"])

    def test_same_day_forecast_is_not_a_conflict(self):
        ds = Dataset()
        sso = next(f for f in ds.forecasts if f["work_item_id"] == "wi_sso")
        acme = next(c for c in ds.commitments if c["id"] == "com_acme_sso")
        self.assertEqual(sso["available_at"], acme["due_at"])
        self.assertEqual(impact(ds, "com_acme_sso", "2026-10-17T10:00:00+05:30")["status"], "no_detected_conflict")

    def test_expected_updates_match_reference_walk(self):
        expected = load("expected/updates.json")
        baseline = Dataset()
        for update in expected["updates"]:
            ds = Dataset()
            ds.apply({"op": "apply_update", "work_item_id": update["work_item_id"],
                      "available_at": update["new_available_at"], "effective_at": expected["preview_created_at"],
                      "decision_id": "dec_test", "forecast_id": "fc_test", "source_id": "src_dec12", "quote": ""})
            self.assert_impacts(ds, expected["as_of"], update["impacts"])
            flagged = sorted(c for c, e in update["impacts"].items() if e["status"] == "date_conflict")
            self.assertEqual(flagged, update["flagged_commitment_ids"], update["id"])
            self.assertNotIn("com_cedar_export", flagged)
            for fid in update["unchanged_forecast_ids"]:
                before = next(f for f in baseline.forecasts if f["id"] == fid)
                self.assertEqual(next(f for f in ds.forecasts if f["id"] == fid), before)
        by_id = {u["id"]: u for u in expected["updates"]}
        self.assertEqual(by_id["upd_permissions_oct23"]["flagged_commitment_ids"], [])
        self.assertEqual(by_id["upd_permissions_oct25"]["flagged_commitment_ids"], ["com_acme_sso"])
        self.assertEqual(by_id["upd_permissions_oct28"]["flagged_commitment_ids"], ["com_acme_sso", "com_birch_audit"])
        self.assertEqual(by_id["upd_permissions_nov10"]["flagged_commitment_ids"],
                         ["com_acme_sso", "com_birch_audit", "com_delta_sso"])
        for update in expected["updates"]:
            for entry in update["impacts"].values():
                if entry["status"] == "date_conflict":
                    self.assertEqual(entry["blocker_work_item_ids"], ["wi_permissions"])
                    self.assertEqual(entry["engineering_owner_id"], "person_priya")

    def test_expected_history_follows_canonical_update(self):
        history = load("expected/history.json")
        forecasts = history["forecasts"]
        previous, current = forecasts
        ds = Dataset()
        seeded = next(f for f in ds.forecasts if f["work_item_id"] == "wi_permissions")
        self.assertEqual(previous["id"], seeded["id"])
        self.assertEqual(previous["available_at"], seeded["available_at"])
        self.assertEqual(previous["valid_from"], seeded["valid_from"])
        self.assertEqual(previous["decision_id"], "DEC-12")
        self.assertEqual(previous["valid_to"], current["valid_from"])
        self.assertEqual(current["valid_to"], None)
        self.assertEqual(current["available_at"], "2026-10-28")
        for placeholder in (current["id"], current["decision_id"], current["valid_from"]):
            self.assertRegex(placeholder, r"^<[a-z_]+>$")
        self.assertIn("DEC-12", {d["id"] for d in ds.decisions})
        self.assertEqual(history["lineage"]["new_decision"]["supersedes_id"], "DEC-12")
        self.assertEqual(history["update_id"], "upd_permissions_oct28")


class ScenarioTests(FixtureCase):
    def scenarios(self):
        paths = sorted((ROOT / "expected" / "scenarios").glob("*.json"))
        self.assertGreaterEqual(len(paths), 10)
        return [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    def test_scenario_ids_unique_and_match_filenames(self):
        paths = sorted((ROOT / "expected" / "scenarios").glob("*.json"))
        ids = [json.loads(p.read_text(encoding="utf-8"))["id"] for p in paths]
        self.assertEqual(ids, [p.stem for p in paths])
        self.assertEqual(len(ids), len(set(ids)))

    def test_scenarios_have_valid_references_and_quotes(self):
        for scenario in self.scenarios():
            ds = scenario_dataset(copy.deepcopy(scenario))
            self.assertEqual(reference_errors(ds), [], scenario["id"])
            self.assertEqual(quote_errors(ds), [], scenario["id"])
            for source in scenario.get("added_sources", []):
                self.assertNotIn(source["id"], Dataset().sources)
                self.assertRegex(source["source_timestamp"], INSTANT_RE)

    def test_scenario_expectations_match_reference_walk(self):
        for scenario in self.scenarios():
            ds = scenario_dataset(copy.deepcopy(scenario))
            expected = scenario["expected"]
            if expected["import"] == "rejected":
                self.assertEqual(expected["reason"], "dependency_cycle", scenario["id"])
                self.assertTrue(find_cycle(ds), scenario["id"])
                continue
            self.assertFalse(find_cycle(ds), scenario["id"])
            for q in expected["queries"]:
                self.assert_impacts(ds, q["as_of"], q["impacts"])

    def test_required_cases_are_covered(self):
        ids = {s["id"] for s in self.scenarios()}
        self.assertTrue({"scn_missing_forecast", "scn_conflicting_forecasts", "scn_missing_owner_no_blocker",
                         "scn_missing_owner_with_blocker", "scn_blockers_different_owners",
                         "scn_dependency_cycle", "scn_chain_too_deep", "scn_edge_removal_ablation",
                         "scn_history_past_interval", "scn_conflicting_forecast_past_due",
                         "scn_conflicting_forecast_other_blocker", "scn_missing_requirement"} <= ids)

    def test_edge_removal_ablation_and_restore(self):
        scenarios = {s["id"]: s for s in self.scenarios()}
        ablated = scenarios["scn_edge_removal_ablation"]["expected"]["queries"][0]["impacts"]
        self.assertEqual(ablated["com_acme_sso"]["status"], "no_detected_conflict")
        self.assertEqual(ablated["com_birch_audit"]["status"], "date_conflict")
        restored = scenarios["scn_edge_removal_restored"]["expected"]["queries"][0]["impacts"]
        canonical = next(u for u in load("expected/updates.json")["updates"] if u["id"] == "upd_permissions_oct28")
        self.assertEqual(restored, canonical["impacts"])

    def test_history_intervals_differ_by_as_of(self):
        scenario = next(s for s in self.scenarios() if s["id"] == "scn_history_past_interval")
        statuses = [q["impacts"]["com_acme_sso"]["status"] for q in scenario["expected"]["queries"]]
        self.assertEqual(statuses, ["date_conflict", "no_detected_conflict", "no_detected_conflict"])
        self.assertEqual(LIVE_UPDATE_TIME, load("expected/updates.json")["preview_created_at"])


if __name__ == "__main__":
    unittest.main()
