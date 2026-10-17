"""Seed loader: Harbor fixtures (plus optional scenario overlay) into FalkorDB.

Graph model written here:
  Nodes  Customer, Commitment, WorkItem, Person, Team, Source, Decision, Forecast,
         Alias, GraphState. All times are epoch ms ints; a null valid_to is an absent property.
  Edges  HAS_COMMITMENT, REQUIRES, DEPENDS_ON, OWNS, ACCOUNT_OWNER, MEMBER_OF,
         RESPONSIBLE_FOR, DISCUSSED (Person -> WorkItem, "who knows what") (all with source_id + quote properties, from relationships.json);
         (WorkItem)-[:HAS_FORECAST]->(Forecast); (Decision)-[:ESTABLISHES]->(Forecast);
         (Decision)-[:REVISES]->(WorkItem); (Decision)-[:SUPERSEDES]->(Decision);
         (Commitment|Forecast|Decision)-[:SUPPORTED_BY {source_id, quote}]->(Source).
  Aliases are Alias nodes {id, text, text_lower, kind} with (Alias)-[:REFERS_TO]->(entity),
         one edge per candidate, so an ambiguous alias has several REFERS_TO edges.

The scenario overlay is a test/seed helper (the operation vocabulary documented in
tests/graph/test_fixtures.py), not the live confirm_decision flow.
"""
import copy
import hashlib
import json
import uuid
from pathlib import Path

from .errors import FixtureError, GraphError
from .timeutil import instant_ms, to_ms

REL_LABELS = {
    "HAS_COMMITMENT": ("Customer", "Commitment"), "REQUIRES": ("Commitment", "WorkItem"),
    "DEPENDS_ON": ("WorkItem", "WorkItem"), "OWNS": ("Person", "WorkItem"),
    "ACCOUNT_OWNER": ("Person", "Customer"), "MEMBER_OF": ("Person", "Team"),
    "RESPONSIBLE_FOR": ("Team", "WorkItem"), "DISCUSSED": ("Person", "WorkItem")}
KIND_LABELS = {"customer": "Customer", "commitment": "Commitment", "work_item": "WorkItem",
               "person": "Person", "team": "Team", "decision": "Decision"}
NODE_LABELS = ["Customer", "Commitment", "WorkItem", "Person", "Team", "Source", "Decision",
               "Forecast", "Alias"]
MAX_HOPS = 4


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_fixtures(fixtures_dir):
    """Read the fixture files into plain dicts/lists (times still ISO strings)."""
    root = Path(fixtures_dir)
    data = {name: _read_json(root / "entities" / (name + ".json"))
            for name in ("customers", "commitments", "work_items", "people", "teams",
                         "relationships", "aliases")}
    data["decisions"] = _read_json(root / "decisions" / "decisions.json")
    data["forecasts"] = _read_json(root / "decisions" / "forecasts.json")
    data["sources"] = [dict(entry, body=(root / "sources" / entry["file"]).read_text(encoding="utf-8"))
                       for entry in _read_json(root / "sources" / "index.json")]
    return data


# ---- scenario overlay
def apply_scenario(data, scenario):
    """Return a copy of data with the scenario's added_sources and operations applied."""
    data = copy.deepcopy(data)
    for source in scenario.get("added_sources", []):
        data["sources"].append(dict(source))
    for op in scenario.get("operations", []):
        _apply_operation(data, op)
    return data


def _edges(data, rel_type, from_id=None, to_id=None):
    return [r for r in data["relationships"] if r["type"] == rel_type
            and from_id in (None, r["from_id"]) and to_id in (None, r["to_id"])]


def _apply_operation(data, op):
    kind = op["op"]
    if kind == "remove_relationship":
        hit = _edges(data, op["type"], op["from_id"], op["to_id"])
        if len(hit) != 1:
            raise FixtureError("remove_relationship matched %d edges: %r" % (len(hit), op))
        data["relationships"].remove(hit[0])
    elif kind == "add_relationship":
        data["relationships"].append(op["relationship"])
    elif kind == "remove_forecast":
        hit = [f for f in data["forecasts"] if f["id"] == op["forecast_id"]]
        if len(hit) != 1:
            raise FixtureError("remove_forecast found no forecast: %r" % op)
        data["forecasts"].remove(hit[0])
    elif kind == "add_forecast":
        data["forecasts"].append(op["forecast"])
    elif kind == "add_decision":
        data["decisions"].append(op["decision"])
    elif kind == "add_work_item":
        data["work_items"].append(op["work_item"])
    elif kind == "remove_owner":
        hit = _edges(data, "OWNS", to_id=op["work_item_id"])
        if not hit:
            raise FixtureError("remove_owner found no OWNS edge: %r" % op)
        for rel in hit:
            data["relationships"].remove(rel)
    elif kind == "apply_update":
        _apply_update(data, op)
    else:
        raise FixtureError("unknown scenario operation %r" % kind)


def _apply_update(data, op):
    open_forecasts = [f for f in data["forecasts"] if f["work_item_id"] == op["work_item_id"]
                      and f["status"] == "accepted" and f["valid_to"] is None]
    if len(open_forecasts) != 1:
        raise FixtureError("apply_update needs exactly one open forecast: %r" % op)
    old = open_forecasts[0]
    if not instant_ms(old["valid_from"]) < instant_ms(op["effective_at"]):
        raise FixtureError("apply_update effective_at is not after the active forecast's valid_from")
    old["valid_to"] = op["effective_at"]
    data["decisions"].append({
        "id": op["decision_id"], "summary": "scenario update", "decided_at": op["effective_at"],
        "status": "approved", "revises_work_item_id": op["work_item_id"],
        "supersedes_id": old["established_by_decision_id"], "source_id": op["source_id"],
        "quote": op["quote"]})
    data["forecasts"].append({
        "id": op["forecast_id"], "work_item_id": op["work_item_id"], "available_at": op["available_at"],
        "valid_from": op["effective_at"], "valid_to": None, "status": "accepted",
        "established_by_decision_id": op["decision_id"], "source_id": op["source_id"],
        "quote": op["quote"]})


# ---- validation (runs before anything is written)
def find_dependency_cycle(data):
    graph = {}
    for rel in _edges(data, "DEPENDS_ON"):
        graph.setdefault(rel["from_id"], []).append(rel["to_id"])
    state = {}

    def visit(node):
        state[node] = "open"
        for nxt in graph.get(node, []):
            if state.get(nxt) == "open" or (nxt not in state and visit(nxt)):
                return True
        state[node] = "done"
        return False
    return any(node not in state and visit(node) for node in list(graph))


def validate(data):
    if find_dependency_cycle(data):
        raise FixtureError("dependency cycle in DEPENDS_ON edges; import rejected")
    ids = {"customer": set(), "commitment": set(), "work_item": set(), "person": set(),
           "team": set(), "decision": set(), "forecast": set(), "source": set()}
    for kind, key in [("customer", "customers"), ("commitment", "commitments"), ("work_item", "work_items"),
                      ("person", "people"), ("team", "teams"), ("decision", "decisions"),
                      ("forecast", "forecasts"), ("source", "sources")]:
        for item in data[key]:
            if item["id"] in ids[kind]:
                raise FixtureError("duplicate %s id %r" % (kind, item["id"]))
            ids[kind].add(item["id"])
    kinds = {"Customer": "customer", "Commitment": "commitment", "WorkItem": "work_item",
             "Person": "person", "Team": "team"}
    for rel in data["relationships"]:
        from_label, to_label = REL_LABELS[rel["type"]]
        if rel["from_id"] not in ids[kinds[from_label]] or rel["to_id"] not in ids[kinds[to_label]]:
            raise FixtureError("relationship references an unknown ID: %r" % rel)
    for f in data["forecasts"]:
        if f["work_item_id"] not in ids["work_item"] or f["established_by_decision_id"] not in ids["decision"]:
            raise FixtureError("forecast %s references an unknown work item or decision" % f["id"])
    for d in data["decisions"]:
        if d["revises_work_item_id"] not in ids["work_item"]:
            raise FixtureError("decision %s revises an unknown work item" % d["id"])
        if d["supersedes_id"] is not None and d["supersedes_id"] not in ids["decision"]:
            raise FixtureError("decision %s supersedes an unknown decision" % d["id"])
    bodies = {s["id"]: s["body"] for s in data["sources"]}
    for rec in data["relationships"] + data["commitments"] + data["decisions"] + data["forecasts"]:
        body = bodies.get(rec["source_id"])
        if body is None or not rec["quote"] or rec["quote"] not in body:
            raise FixtureError("quote is not an exact substring of its source: %r" % rec)
    for alias in data["aliases"]:
        for cid in alias["candidate_ids"]:
            if cid not in ids[alias["kind"]]:
                raise FixtureError("alias %r points at unknown %s %r" % (alias["alias"], alias["kind"], cid))


# ---- writing
def _node_rows(data):
    """label -> list of property maps with times converted to epoch ms."""
    return {
        "Customer": [{"id": c["id"], "name": c["name"], "synthetic_contract_value": c["synthetic_contract_value"]}
                     for c in data["customers"]],
        "Commitment": [{"id": c["id"], "title": c["title"], "due_at": to_ms(c["due_at"]),
                        "status": c["status"], "source_id": c["source_id"], "quote": c["quote"]}
                       for c in data["commitments"]],
        "WorkItem": [{"id": w["id"], "name": w["name"], "kind": w["kind"]} for w in data["work_items"]],
        "Person": [{"id": p["id"], "name": p["name"]} for p in data["people"]],
        "Team": [{"id": t["id"], "name": t["name"]} for t in data["teams"]],
        "Source": [{"id": s["id"], "type": s["type"], "title": s["title"], "body": s["body"],
                    "source_timestamp": instant_ms(s["source_timestamp"]),
                    "content_hash": hashlib.sha256(s["body"].encode("utf-8")).hexdigest()}
                   for s in data["sources"]],
        "Decision": [{"id": d["id"], "summary": d["summary"], "decided_at": instant_ms(d["decided_at"]),
                      "status": d["status"], "source_id": d["source_id"], "quote": d["quote"]}
                     for d in data["decisions"]],
        "Forecast": [dict({"id": f["id"], "available_at": to_ms(f["available_at"]),
                           "valid_from": instant_ms(f["valid_from"]), "status": f["status"],
                           "source_id": f["source_id"], "quote": f["quote"]},
                          **({"valid_to": instant_ms(f["valid_to"])} if f["valid_to"] else {}))
                     for f in data["forecasts"]],
        "Alias": [{"id": "alias:%s:%s" % (a["kind"], a["alias"].lower()), "text": a["alias"],
                   "text_lower": a["alias"].lower(), "kind": a["kind"]} for a in data["aliases"]],
    }


def _edge_statements(data):
    """(label_from, label_to, edge_type, rows) for every edge, rows keyed from_id/to_id."""
    by_type = {}
    for rel in data["relationships"]:
        by_type.setdefault(rel["type"], []).append(rel)
    for rel_type, rows in by_type.items():
        yield (*REL_LABELS[rel_type], rel_type,
               [{"from_id": r["from_id"], "to_id": r["to_id"], "source_id": r["source_id"], "quote": r["quote"]}
                for r in rows])
    forecasts = data["forecasts"]
    yield "WorkItem", "Forecast", "HAS_FORECAST", [
        {"from_id": f["work_item_id"], "to_id": f["id"]} for f in forecasts]
    yield "Decision", "Forecast", "ESTABLISHES", [
        {"from_id": f["established_by_decision_id"], "to_id": f["id"]} for f in forecasts]
    yield "Decision", "WorkItem", "REVISES", [
        {"from_id": d["id"], "to_id": d["revises_work_item_id"]} for d in data["decisions"]]
    yield "Decision", "Decision", "SUPERSEDES", [
        {"from_id": d["id"], "to_id": d["supersedes_id"]} for d in data["decisions"] if d["supersedes_id"]]
    for label, key in (("Commitment", "commitments"), ("Forecast", "forecasts"), ("Decision", "decisions")):
        yield label, "Source", "SUPPORTED_BY", [
            {"from_id": r["id"], "to_id": r["source_id"], "source_id": r["source_id"], "quote": r["quote"]}
            for r in data[key]]
    for kind, label in KIND_LABELS.items():
        yield "Alias", label, "REFERS_TO", [
            {"from_id": "alias:%s:%s" % (a["kind"], a["alias"].lower()), "to_id": cid}
            for a in data["aliases"] if a["kind"] == kind for cid in a["candidate_ids"]]


# ---- schema of what is written: exact keys and types, checked before any write
TEXT, MS, NUMBER = "text", "epoch_ms", "number"
NODE_SCHEMA = {
    "Customer": {"id": TEXT, "name": TEXT, "synthetic_contract_value": NUMBER},
    "Commitment": {"id": TEXT, "title": TEXT, "due_at": MS, "status": TEXT, "source_id": TEXT, "quote": TEXT},
    "WorkItem": {"id": TEXT, "name": TEXT, "kind": TEXT},
    "Person": {"id": TEXT, "name": TEXT},
    "Team": {"id": TEXT, "name": TEXT},
    "Source": {"id": TEXT, "type": TEXT, "title": TEXT, "body": TEXT, "source_timestamp": MS, "content_hash": TEXT},
    "Decision": {"id": TEXT, "summary": TEXT, "decided_at": MS, "status": TEXT, "source_id": TEXT, "quote": TEXT},
    "Forecast": {"id": TEXT, "available_at": MS, "valid_from": MS, "status": TEXT, "source_id": TEXT, "quote": TEXT},
    "Alias": {"id": TEXT, "text": TEXT, "text_lower": TEXT, "kind": TEXT},
}
OPTIONAL_NODE_PROPS = {"Forecast": {"valid_to": MS}}
EDGE_SCHEMA = {"from_id": TEXT, "to_id": TEXT}
EDGE_PROVENANCE = {"source_id": TEXT, "quote": TEXT}
WORK_ITEM_KINDS = ("feature", "component", "project")  # the API's PathNode.kind values


def _type_ok(value, kind):
    if kind == TEXT:
        return isinstance(value, str)
    if isinstance(value, bool):  # bool is an int subclass; never a valid number or time here
        return False
    if kind == MS:
        return isinstance(value, int)
    return isinstance(value, (int, float)) and value == value and abs(value) != float("inf")


def _check_props(where, props, required, optional=None):
    optional = optional or {}
    keys = set(props)
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        raise FixtureError("%s has properties %s, expected %s" % (where, sorted(keys), sorted(required)))
    for key, value in props.items():
        if not _type_ok(value, required.get(key) or optional[key]):
            raise FixtureError("%s.%s has unsupported value %r (expected %s)"
                               % (where, key, value, required.get(key) or optional[key]))
    if not props.get("id", "x"):
        raise FixtureError("%s has an empty id" % where)


def check_schema(node_rows, edge_statements):
    """Every row about to be written has exactly the expected keys and storable types."""
    for label, rows in node_rows.items():
        for row in rows:
            _check_props("%s %r" % (label, row.get("id")), row, NODE_SCHEMA[label], OPTIONAL_NODE_PROPS.get(label))
    for row in node_rows["WorkItem"]:
        if row["kind"] not in WORK_ITEM_KINDS:
            raise FixtureError("WorkItem %r has kind %r, expected one of %s" % (row["id"], row["kind"], WORK_ITEM_KINDS))
    for _, _, edge_type, rows in edge_statements:
        for row in rows:
            schema = dict(EDGE_SCHEMA, **(EDGE_PROVENANCE if "quote" in rows[0] else {}))
            _check_props("%s edge %r" % (edge_type, row.get("from_id")), row, schema)


def prepare(data):
    """Validate data and convert it to node rows and edge statements, touching nothing.

    Every malformed field (bad date, missing key, wrong or unstorable type) surfaces here
    as a FixtureError. write_graph also stages the load, so even an error only the
    database detects cannot reach the live graph.
    """
    try:
        validate(data)
        node_rows, edge_statements = _node_rows(data), list(_edge_statements(data))
        check_schema(node_rows, edge_statements)
        return node_rows, edge_statements
    except FixtureError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise FixtureError("malformed fixture data (%s: %s); import rejected" % (type(exc).__name__, exc)) from exc


def write_graph(client, data):
    """Replace the client's graph with data. Returns the new dataset_id.

    The new graph is built in a separate staging graph. Only when every write there has
    succeeded does one atomic rename replace the live graph, so a failed load (including
    a rejection only the database detects) never touches the live graph.
    """
    node_rows, edge_statements = prepare(data)
    staging = client.for_graph("%s__staging_%s" % (client.graph_name, uuid.uuid4().hex[:8]))
    try:
        dataset_id = _load(staging, node_rows, edge_statements)
        staging.move_to(client.graph_name)
        return dataset_id
    finally:
        _drop_staging(staging)  # no-op after a successful move


def _drop_staging(staging):
    """Best-effort removal of a staging graph left by a failed load.

    The outcome is already decided when this runs, so a cleanup error must not hide the
    error that made the load fail.
    """
    try:
        staging.delete_graph()
    except GraphError:
        pass


def _load(client, node_rows, edge_statements):
    """Write prepared rows into client's (empty) graph and return the new dataset_id."""
    client.delete_graph()
    for label in NODE_LABELS + ["GraphState", "Action", "RequestRecord"]:
        client.write("CREATE INDEX FOR (n:%s) ON (n.id)" % label)
    for label, rows in node_rows.items():
        if rows:
            client.write("UNWIND $rows AS r CREATE (n:%s) SET n = r" % label, {"rows": rows})
    for from_label, to_label, edge_type, rows in edge_statements:
        if not rows:
            continue
        props = " {source_id: r.source_id, quote: r.quote}" if "quote" in rows[0] else ""
        result = client.write(
            "UNWIND $rows AS r MATCH (a:%s {id: r.from_id}) MATCH (b:%s {id: r.to_id}) "
            "CREATE (a)-[:%s%s]->(b)" % (from_label, to_label, edge_type, props), {"rows": rows})
        if result["relationships_created"] != len(rows):
            raise FixtureError("%s: created %d of %d edges (dangling endpoint)"
                               % (edge_type, result["relationships_created"], len(rows)))
    dataset_id = uuid.uuid4().hex
    client.write("CREATE (:GraphState {id: 'workspace', dataset_id: $dataset_id, revision: 0})",
                 {"dataset_id": dataset_id})
    return dataset_id


def seed_demo(client, fixtures_dir, scenario=None):
    """Validate, then replace the graph with the fixtures (and optional scenario overlay)."""
    data = load_fixtures(fixtures_dir)
    if scenario:
        try:
            data = apply_scenario(data, scenario)
        except FixtureError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FixtureError("malformed scenario (%s: %s); import rejected" % (type(exc).__name__, exc)) from exc
    return write_graph(client, data)
