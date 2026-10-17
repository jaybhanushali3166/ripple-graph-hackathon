"""Synchronous, read-side GraphRepository. Returns plain dicts, never FalkorDB objects.

Traversal, forecast activity, owner lookup and the due-date comparison come from the
Cypher in backend/queries/*.cypher; this module groups the rows and applies the R1
status/owner rules. Downstream forecasts are never recalculated.
"""
from pathlib import Path

from .client import GraphClient
from .errors import InconsistentRead, NotFound
from .seed import KIND_LABELS, MAX_HOPS, seed_demo
from .timeutil import ist_date

QUERY_DIR = Path(__file__).resolve().parents[2] / "queries"

# Warning codes appear as the prefix of a reason ("<code>: <message>").
WARNING_CODES = ("missing_forecast", "conflicting_forecasts", "missing_engineering_owner",
                 "ambiguous_engineering_owner", "missing_account_owner", "ambiguous_account_owner",
                 "depth_limit_exceeded", "missing_requirement", "missing_customer",
                 "missing_forecast_provenance")
OWNER_CODES = WARNING_CODES[2:6]

READ_ATTEMPTS = 3
_query_cache = {}


def load_query(name):
    if name not in _query_cache:
        _query_cache[name] = (QUERY_DIR / (name + ".cypher")).read_text(encoding="utf-8")
    return _query_cache[name]


def warning_code(reason):
    code = reason.split(":", 1)[0]
    return code if code in WARNING_CODES else None


def _citation(source_id, quote):
    return {"source_id": source_id, "quote": quote}


class GraphRepository:
    def __init__(self, client=None):
        self.client = client or GraphClient()

    # ---- seeding (test/demo helper)
    def seed_demo(self, fixtures_dir, scenario=None):
        return seed_demo(self.client, fixtures_dir, scenario)

    # ---- version and sources
    def get_version(self):
        rows = self.client.read(load_query("graph_state"))
        if not rows:
            raise NotFound("graph has no GraphState; seed it first")
        dataset_id, revision = rows[0]
        return "%s:%d" % (dataset_id, revision)

    def get_source(self, source_id):
        rows = self.client.read(load_query("source_by_id"), {"id": source_id})
        if not rows:
            raise NotFound("source %r not found" % source_id)
        keys = ("id", "type", "title", "body", "source_timestamp", "content_hash")
        return dict(zip(keys, rows[0]))

    def get_history(self, work_item_id):
        """Accepted forecasts of a work item, oldest valid_from first, with establishing Decisions."""
        version, forecasts = self._consistent(lambda: self._history(work_item_id))
        return {"evidence_version": version, "forecasts": forecasts}

    def _history(self, work_item_id):
        rows = self.client.read(load_query("history_forecasts"), {"wid": work_item_id})
        if not rows:
            raise NotFound("work item %r not found" % work_item_id)
        quotes = {fid: (fq, dq) for fid, fq, dq in
                  self.client.read(load_query("history_citations"), {"wid": work_item_id})}
        forecasts = []
        for _, fid, available_at, valid_from, valid_to, decision_id, supersedes_id, summary in rows:
            if fid is None:
                continue  # work item exists but has no accepted forecast
            fq, dq = quotes.get(fid, ([], []))
            cited = []
            for src, quote in fq + dq:  # forecast quote first; drop an identical decision quote
                if src and _citation(src, quote) not in cited:
                    cited.append(_citation(src, quote))
            forecasts.append({"id": fid, "available_at": available_at, "valid_from": valid_from,
                              "valid_to": valid_to, "decision_id": decision_id,
                              "supersedes_id": supersedes_id, "decision_summary": summary,
                              "citations": cited})
        return sorted(forecasts, key=lambda f: (f["valid_from"], f["id"]))

    # ---- who knows what
    def get_experts(self, work_item_id):
        """People who know a work item, strongest signal first.

        Owning it scores 3, each source where a person discussed it scores 1, and being on
        the responsible team scores 1. Scores only rank; every reason keeps its quote.
        """
        def read():
            if not self.client.read("MATCH (w:WorkItem {id: $wid}) RETURN w.id", {"wid": work_item_id}):
                raise NotFound("work item %r not found" % work_item_id)
            people = {}
            for person_id, name, relation, source_id, quote in self.client.read(load_query("experts"),
                                                                                  {"wid": work_item_id}):
                entry = people.setdefault(person_id, {"id": person_id, "name": name, "score": 0, "reasons": []})
                kind, _, team = relation.partition(":")
                reason = {"kind": kind.lower(), "source_id": source_id, "quote": quote}
                if team:
                    reason["team"] = team
                if reason in entry["reasons"]:
                    continue
                entry["reasons"].append(reason)
                entry["score"] += 3 if kind == "OWNS" else 1
            return sorted(people.values(), key=lambda p: (-p["score"], p["name"]))
        version, experts = self._consistent(read)
        return {"evidence_version": version, "work_item_id": work_item_id, "experts": experts}

    # ---- whole-graph view
    def get_graph(self):
        """Customers, commitments and work items with the edges that connect them, for display."""
        def read():
            nodes = [{"id": i, "label": label, "kind": kind}
                     for i, label, kind in self.client.read(load_query("graph_nodes"))]
            edges = [{"from_id": a, "to_id": b, "relation": rel, "source_id": src}
                     for a, b, rel, src in self.client.read(load_query("graph_edges"))]
            return {"nodes": sorted(nodes, key=lambda n: n["id"]),
                    "edges": sorted(edges, key=lambda e: (e["relation"], e["from_id"], e["to_id"]))}
        version, graph = self._consistent(read)
        return dict(graph, evidence_version=version)

    def list_decisions(self):
        return [{"id": d, "revises_work_item_id": w} for d, w in self.client.read(load_query("decisions"))]

    def list_sources(self):
        rows = self.client.read("MATCH (s:Source) RETURN s.id, s.type, s.title, s.source_timestamp ORDER BY s.id")
        return [{"id": i, "type": t, "title": title, "source_timestamp": ts} for i, t, title, ts in rows]

    # ---- impacts
    def list_impacts(self, as_of_ms):
        version, impacts = self._consistent_impacts(as_of_ms, None)
        warnings = ["%s: %s" % (i["commitment_id"], r)
                    for i in impacts for r in i["reasons"] if warning_code(r)]
        truncated = any(r.startswith("depth_limit_exceeded") for i in impacts for r in i["reasons"])
        return {"evidence_version": version, "as_of": as_of_ms, "impacts": impacts,
                "completeness": {"complete": not warnings, "truncated": truncated, "warnings": warnings}}

    def get_evidence(self, commitment_id, as_of_ms):
        impacts = self._consistent_impacts(as_of_ms, commitment_id)[1]
        if not impacts:
            raise NotFound("open commitment %r not found" % commitment_id)
        return impacts[0]

    def get_owners(self, commitment_id, as_of_ms):
        impact = self.get_evidence(commitment_id, as_of_ms)
        return {"engineering_owner": impact["engineering_owner"], "account_owner": impact["account_owner"],
                "warnings": [r for r in impact["reasons"] if warning_code(r) in OWNER_CODES]}

    def _consistent_impacts(self, as_of_ms, commitment_id):
        return self._consistent(lambda: self._impacts(as_of_ms, commitment_id))

    def _consistent(self, read):
        """Run a multi-query read, retrying if the knowledge revision moved meanwhile."""
        for _ in range(READ_ATTEMPTS):
            version = self.get_version()
            result = read()
            if self.get_version() == version:
                return version, result
        raise InconsistentRead("knowledge revision changed during %d read attempts" % READ_ATTEMPTS)

    def _impacts(self, as_of_ms, commitment_id):
        params = {"as_of": as_of_ms, "cid": commitment_id}
        commitments = {}
        for row in self.client.read(load_query("open_commitments"), {"cid": commitment_id}):
            commitments.setdefault(row[0], row)
        if not commitments:
            return []
        path_rows = self.client.read(load_query("impact_paths"), {"cid": commitment_id})
        deep = {r[0] for r in self.client.read(load_query("impact_depth_probe"), {"cid": commitment_id})}
        blockers = self.client.read(load_query("impact_blockers"), params)
        counts = self.client.read(load_query("impact_forecast_counts"), params)
        work_items = {r[0]: {"name": r[1], "kind": r[2]} for r in self.client.read(load_query("work_items"))}
        owners = self._group_owners("owners")
        account_owners = self._group_owners("account_owners")

        paths_by_commitment = {}
        for row in path_rows:
            paths_by_commitment.setdefault(row[0], []).append(row)
        impacts = [self._build_impact(commitment, paths_by_commitment.get(cid, []), deep, blockers, counts,
                                      work_items, owners, account_owners)
                   for cid, commitment in commitments.items()]
        return sorted(impacts, key=lambda i: (i["due_at"], i["commitment_id"]))

    def _group_owners(self, query_name):
        grouped = {}
        for target_id, person_id, name, source_id, quote in self.client.read(load_query(query_name)):
            grouped.setdefault(target_id, []).append(
                {"id": person_id, "name": name, "source_id": source_id, "quote": quote})
        return grouped

    def _build_impact(self, commitment, rows, deep, blockers, counts, work_items, owners, account_owners):
        cid, title, due_at, cust_id, cust_name, hc_source, hc_quote = commitment
        requires = {row[3]: (row[1], row[2]) for row in rows}  # root id -> (source_id, quote)
        roots = sorted(requires)
        reasons = []
        if cust_id is None:
            reasons.append("missing_customer: %s has no HAS_COMMITMENT customer" % cid)
        if not roots:
            reasons.append("missing_requirement: %s has no required work item" % cid)

        # Paths: keep every maximal path (drop prefixes of longer ones), in graph direction.
        raw = {(tuple(r[4]), tuple(r[5]), tuple(r[6])) for r in rows}
        maximal = [p for p in raw if not any(q != p and q[0][:len(p[0])] == p[0] for q in raw)]
        paths, edge_citations = [], []
        for node_ids, edge_sources, edge_quotes in sorted(maximal):
            root_id = node_ids[0]
            nodes = [{"id": cust_id, "label": cust_name, "kind": "customer"}] if cust_id else []
            nodes.append({"id": cid, "label": title, "kind": "commitment"})
            nodes += [{"id": n, "label": work_items[n]["name"], "kind": work_items[n]["kind"]} for n in node_ids]
            edges = [{"from_id": cust_id, "to_id": cid, "relation": "HAS_COMMITMENT", "source_id": hc_source}] \
                if cust_id else []
            edges.append({"from_id": cid, "to_id": root_id, "relation": "REQUIRES",
                          "source_id": requires[root_id][0]})
            edge_citations.append(_citation(requires[root_id][0], requires[root_id][1]))
            for i, (src, quote) in enumerate(zip(edge_sources, edge_quotes)):
                edges.append({"from_id": node_ids[i], "to_id": node_ids[i + 1], "relation": "DEPENDS_ON",
                              "source_id": src})
                edge_citations.append(_citation(src, quote))
            paths.append({"nodes": nodes, "edges": edges})

        # Evidence gaps. A work item with several active forecasts is conflicting, never a blocker.
        conflicted = set()
        for _, wi_id, active in sorted(c for c in counts if c[0] == cid):
            if active == 0:
                reasons.append("missing_forecast: %s has no active accepted forecast" % wi_id)
            elif active > 1:
                conflicted.add(wi_id)
                reasons.append("conflicting_forecasts: %s has %d active accepted forecasts" % (wi_id, active))
        if cid in deep:
            reasons.append("depth_limit_exceeded: dependencies continue beyond %d hops" % MAX_HOPS)

        # Confirmed blockers: past due, single active forecast, with an establishing Decision.
        blocker_list, blocker_citations = [], []
        for row in sorted(b for b in blockers if b[0] == cid):
            _, wi_id, wi_name, fc_id, available_at, fc_source, fc_quote, dec_id, dec_source, dec_quote = row
            if wi_id in conflicted:
                continue
            if dec_id is None:
                reasons.append("missing_forecast_provenance: forecast %s of %s has no establishing decision"
                               % (fc_id, wi_id))
                continue
            blocker_list.append({"work_item_id": wi_id, "name": wi_name, "forecast_id": fc_id,
                                 "available_at": available_at, "decision_id": dec_id})
            blocker_citations += [_citation(fc_source, fc_quote), _citation(dec_source, dec_quote)]
            reasons.append("dependency_after_due: %s is forecast available %s, after %s is due %s"
                           % (wi_id, ist_date(available_at), cid, ist_date(due_at)))

        # Owners: unique owner across blockers, else across required roots.
        subjects = sorted({b["work_item_id"] for b in blocker_list}) or roots
        eng_sets = [owners.get(w, []) for w in subjects]
        engineering_owner = None
        if not subjects:
            pass  # missing_requirement already explains this
        elif any(not s for s in eng_sets):
            reasons.append("missing_engineering_owner: no owner recorded for %s"
                           % ", ".join(w for w, s in zip(subjects, eng_sets) if not s))
        elif len({o["id"] for s in eng_sets for o in s}) > 1:
            reasons.append("ambiguous_engineering_owner: %s have different owners" % ", ".join(subjects))
        else:
            engineering_owner = eng_sets[0][0]
        account = account_owners.get(cust_id, []) if cust_id else []
        account_owner = account[0] if len(account) == 1 else None
        if cust_id and not account:
            reasons.append("missing_account_owner: no account owner for %s" % cust_id)
        elif len(account) > 1:
            reasons.append("ambiguous_account_owner: %s has several account owners" % cust_id)

        owner_citations = [_citation(o["source_id"], o["quote"]) for o in
                           ([engineering_owner] if engineering_owner else []) + ([account_owner] if account_owner else [])]
        status = ("date_conflict" if blocker_list else
                  "needs_verification" if any(warning_code(r) for r in reasons) else "no_detected_conflict")
        citations = []
        head = [_citation(hc_source, hc_quote)] if cust_id else []
        for c in head + edge_citations + blocker_citations + owner_citations:
            if c not in citations:
                citations.append(c)
        return {"commitment_id": cid, "customer": {"id": cust_id or "", "name": cust_name or ""}, "title": title,
                "due_at": due_at, "status": status, "reasons": reasons, "blockers": blocker_list,
                "paths": paths, "engineering_owner": _person(engineering_owner),
                "account_owner": _person(account_owner), "citations": citations}

    # ---- entity resolution
    def resolve_entity(self, query, kind=None):
        """All candidates matching id, name or alias (case-insensitive, exact). Never picks one."""
        q = query.strip().lower()
        labels = {kind: KIND_LABELS[kind]} if kind else KIND_LABELS
        if kind and kind not in KIND_LABELS:
            return []
        found = {}
        for kind_name, label in labels.items():
            cypher = load_query("resolve_by_label").replace("__LABEL__", label)  # label from fixed table
            for entity_id, name in self.client.read(cypher, {"q": q}):
                found.setdefault((kind_name, entity_id), {"id": entity_id, "kind": kind_name, "name": name,
                                                          "matched_by": "id_or_name"})
        label_to_kind = {label: k for k, label in KIND_LABELS.items()}
        for entity_id, label, name in self.client.read(load_query("resolve_by_alias"), {"q": q}):
            entity_kind = label_to_kind[label]
            if kind is None or entity_kind == kind:
                found.setdefault((entity_kind, entity_id), {"id": entity_id, "kind": entity_kind, "name": name,
                                                            "matched_by": "alias"})
        return sorted(found.values(), key=lambda c: (c["kind"], c["id"]))

    # ---- writes (logic lives in writes.py)
    def _writes(self):
        from .writes import GraphWrites  # writes imports load_query from this module
        return GraphWrites(self.client, self.get_version)

    def confirm_decision(self, proposal, source, expected_version, idempotency_key, now_ms=None):
        return self._writes().confirm_decision(proposal, source, expected_version, idempotency_key, now_ms)

    def replay_confirm(self, proposal, source, expected_version, idempotency_key):
        return self._writes().replay_confirm(proposal, source, expected_version, idempotency_key)

    def save_action(self, action, expected_version, idempotency_key, now_ms=None):
        return self._writes().save_action(action, expected_version, idempotency_key, now_ms)

    def list_actions(self, commitment_id):
        return self._writes().list_actions(commitment_id)

    def set_dependency(self, from_id, to_id, present, source_id, quote, expected_version):
        return self._writes().set_dependency(from_id, to_id, present, source_id, quote, expected_version)


def _person(owner):
    return {"id": owner["id"], "name": owner["name"]} if owner else None
