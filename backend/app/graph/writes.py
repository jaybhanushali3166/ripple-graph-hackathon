"""Write side of the graph: confirm_decision, save_action and list_actions.

Every mutation is one Cypher statement gated by the GraphState {dataset_id, revision}
match, so a stale version creates and changes nothing. Validation runs first and raises
typed errors without writing; the gate is what makes overlapping writers safe. A request
that fails validation or the gate re-checks replay and version first, so losing a race
reports StaleEvidence (or the winner's identical result), never ReviewRequired.
Idempotency records (RequestRecord) are written inside the same statement as the facts
they describe, scoped by dataset, operation and key.
"""
import hashlib
import json
import time

from .errors import (IdempotencyConflict, NotFound, ReviewRequired, StaleEvidence)
from .repository import load_query
from .timeutil import ist_date

ACTION_KINDS = ("internal_escalation", "customer_update")


def _sha(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_version(version):
    dataset_id, _, revision = str(version).rpartition(":")
    if not dataset_id or not revision.isdigit():
        raise StaleEvidence("malformed evidence version %r" % (version,))
    return dataset_id, int(revision)


def _now(now_ms):
    return int(time.time() * 1000) if now_ms is None else now_ms


def _require_text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ReviewRequired("%s must be a nonempty string" % what)


class GraphWrites:
    def __init__(self, client, current_version):
        self.client = client
        self.current_version = current_version  # callable returning "dataset:revision"

    # ---- idempotency
    def _request_id(self, dataset_id, operation, key):
        return "req_" + _sha(dataset_id, operation, key)[:32]

    def _replay(self, dataset_id, operation, key, request_hash):
        """Stored result for an identical earlier request, None if the key is new."""
        rows = self.client.read(load_query("request_by_key"), {
            "id": self._request_id(dataset_id, operation, key), "dataset": dataset_id,
            "operation": operation, "key": key})
        if not rows:
            return None
        stored_hash, result_json = rows[0]
        if stored_hash != request_hash:
            raise IdempotencyConflict("idempotency key %r was already used with a different request" % key)
        return json.loads(result_json)

    def _raced(self, dataset_id, revision, operation, key, request_hash):
        """After a failure, check whether a concurrent writer explains it.

        Returns the stored result when an identical request won, raises StaleEvidence when
        the version moved on, and returns None when the failure is the request's own.
        """
        replay = self._replay(dataset_id, operation, key, request_hash)
        if replay is not None:
            return replay
        current = self.current_version()
        if current != "%s:%d" % (dataset_id, revision):
            raise StaleEvidence("evidence version is %s, not %s:%d" % (current, dataset_id, revision),
                                {"current_version": current})
        return None

    def _fail_gate(self, dataset_id, revision, operation, key, request_hash):
        """The gated write matched nothing: report a replay won by a racer, else stale evidence."""
        replay = self._raced(dataset_id, revision, operation, key, request_hash)
        if replay is not None:
            return replay
        raise ReviewRequired("graph changed under the request; review again")

    # ---- confirm_decision
    def replay_confirm(self, proposal, source, expected_version, idempotency_key):
        """The stored result of an identical completed confirm, else None. Writes nothing.

        For callers that must answer a replay before their own rejections (preview expiry).
        """
        dataset_id, _ = _parse_version(expected_version)
        request_hash = _confirm_hash(proposal, source, expected_version)
        return self._replay(dataset_id, "confirm_decision", idempotency_key, request_hash)

    def confirm_decision(self, proposal, source, expected_version, idempotency_key, now_ms=None):
        dataset_id, revision = _parse_version(expected_version)
        request_hash = _confirm_hash(proposal, source, expected_version)
        replay = self._replay(dataset_id, "confirm_decision", idempotency_key, request_hash)
        if replay is not None:
            return replay

        now = _now(now_ms)
        wi_id = proposal["work_item_id"]
        available_at, effective_at = proposal["available_at"], proposal["effective_at"]
        self._require_current(expected_version)
        decision_id = "dec_" + _sha(dataset_id, source["id"], wi_id, available_at)[:16]
        forecast_id = "fc_" + _sha(dataset_id, source["id"], wi_id, available_at)[:16]
        try:
            wi_name = self._validate_confirm(proposal, source, wi_id, effective_at, now)
            taken = {r[0] for r in self.client.read(load_query("confirm_ids"), {"ids": [decision_id, forecast_id]})}
            if taken:
                raise ReviewRequired("this note already produced %s; submit a new note" % ", ".join(sorted(taken)))
        except (ReviewRequired, NotFound):
            # A writer that committed after _require_current makes validation see its facts
            # (e.g. its forecast's valid_from). Report that as the race it is, not a review error.
            replay = self._raced(dataset_id, revision, "confirm_decision", idempotency_key, request_hash)
            if replay is not None:
                return replay
            raise
        result = {"decision_id": decision_id, "evidence_version": "%s:%d" % (dataset_id, revision + 1),
                  "changed_work_item_ids": [wi_id]}
        written = self.client.write(load_query("confirm_decision"), {
            "dataset": dataset_id, "expected_revision": revision, "work_item_id": wi_id,
            "effective_at": effective_at, "available_at": available_at, "now": now,
            "source_id": source["id"], "source_type": source["type"], "source_title": source["title"],
            "source_body": source["body"], "source_timestamp": source["source_timestamp"],
            "content_hash": _sha256_body(source["body"]), "quote": proposal["evidence_quote"],
            "forecast_id": forecast_id, "decision_id": decision_id,
            "summary": "%s delivery set to %s (IST)" % (wi_name, ist_date(available_at)),
            "request_id": self._request_id(dataset_id, "confirm_decision", idempotency_key),
            "key": idempotency_key, "request_hash": request_hash, "result_json": _canonical(result)})
        if not written["rows"]:
            return self._fail_gate(dataset_id, revision, "confirm_decision", idempotency_key, request_hash)
        return result

    def _validate_confirm(self, proposal, source, wi_id, effective_at, now):
        rows = self.client.read(load_query("confirm_context"), {"id": wi_id})
        if not rows:
            raise NotFound("work item %r not found" % wi_id)
        active = {r[1]: r for r in rows if r[1] is not None}
        if len(active) != 1:
            raise ReviewRequired("%s has %d active accepted forecasts; exactly one is required"
                                 % (wi_id, len(active)))
        forecast_id, valid_from, active_available_at = next((r[1], r[2], r[4]) for r in rows if r[1] is not None)
        establishing = {r[3] for r in rows if r[3] is not None}
        if len(establishing) != 1:
            raise ReviewRequired("active forecast %s needs exactly one establishing decision" % forecast_id)
        owners = {r[0] for r in self.client.read(load_query("confirm_owners"), {"id": wi_id})}
        if owners != {proposal["owner_id"]}:
            raise ReviewRequired("owner %r does not match the recorded owner of %s" % (proposal["owner_id"], wi_id))
        if proposal["available_at"] == active_available_at:
            raise ReviewRequired("%s is already forecast available at that date; nothing to update" % wi_id)
        _require_text(proposal.get("evidence_quote"), "evidence_quote")
        if proposal["evidence_quote"] not in source["body"]:
            raise ReviewRequired("evidence_quote is not an exact substring of the source body")
        if not valid_from < effective_at <= now:
            raise ReviewRequired("effective_at must be after the active forecast's valid_from and not in the future")
        supersedes_id = proposal.get("supersedes_id")
        if supersedes_id is not None and supersedes_id not in establishing:
            raise ReviewRequired("supersedes_id %r is not the active forecast's establishing decision" % supersedes_id)
        stored = self.client.read(load_query("source_by_id"), {"id": source["id"]})
        if stored and stored[0][5] != _sha256_body(source["body"]):
            raise ReviewRequired("source %r already exists with different content" % source["id"])
        return rows[0][5] or wi_id

    def _require_current(self, expected_version):
        current = self.current_version()
        if expected_version != current:
            raise StaleEvidence("evidence version is %s, not %s" % (current, expected_version),
                                {"current_version": current})

    # ---- save_action
    def save_action(self, action, expected_version, idempotency_key, now_ms=None):
        dataset_id, revision = _parse_version(expected_version)
        request_hash = _sha(_canonical({"action": action, "expected_version": expected_version}))
        replay = self._replay(dataset_id, "save_action", idempotency_key, request_hash)
        if replay is not None:
            return replay

        self._require_current(expected_version)
        try:
            decision_ids = self._validate_action(action)
        except (ReviewRequired, NotFound):
            replay = self._raced(dataset_id, revision, "save_action", idempotency_key, request_hash)
            if replay is not None:
                return replay
            raise

        now = _now(now_ms)
        result = {"action_id": "act_" + _sha(dataset_id, idempotency_key)[:16], "status": "reviewed",
                  "evidence_version": expected_version, "created_at": now}
        written = self.client.write(load_query("action_save"), {
            "dataset": dataset_id, "expected_revision": revision, "commitment_id": action["commitment_id"],
            "assignee_id": action["assignee_id"], "decision_ids": decision_ids,
            "decision_count": len(decision_ids), "action_id": result["action_id"], "kind": action["kind"],
            "body": action["body"], "now": now, "evidence_version": expected_version,
            "citations_json": _canonical(action["citations"]),
            "request_id": self._request_id(dataset_id, "save_action", idempotency_key),
            "key": idempotency_key, "request_hash": request_hash, "result_json": _canonical(result)})
        if not written["rows"] or not written["rows"][0][0]:  # RETURN count(*) yields a 0 row when nothing matched
            return self._fail_gate(dataset_id, revision, "save_action", idempotency_key, request_hash)
        return result

    def _validate_action(self, action):
        if not self.client.read(load_query("action_commitment"), {"id": action["commitment_id"]}):
            raise NotFound("commitment %r not found" % action["commitment_id"])
        if not action.get("assignee_id") or not self.client.read(
                load_query("action_person"), {"id": action["assignee_id"]}):
            raise NotFound("assignee %r not found" % action.get("assignee_id"))
        if action.get("kind") not in ACTION_KINDS:
            raise ReviewRequired("kind must be one of %s" % ", ".join(ACTION_KINDS))
        _require_text(action.get("body"), "body")
        citations = action.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ReviewRequired("at least one citation is required")
        decision_ids = sorted(set(action.get("based_on_decision_ids") or []))
        if not decision_ids:
            raise ReviewRequired("based_on_decision_ids must not be empty")
        found = {r[0] for r in self.client.read(load_query("action_decisions"), {"ids": decision_ids})}
        if found != set(decision_ids):
            raise NotFound("decisions not found: %s" % ", ".join(sorted(set(decision_ids) - found)))
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {"source_id", "quote"}:
                raise ReviewRequired("each citation needs exactly source_id and quote")
            _require_text(citation["quote"], "citation quote")
            rows = self.client.read(load_query("source_by_id"), {"id": citation["source_id"]})
            if not rows:
                raise NotFound("source %r not found" % citation["source_id"])
            if citation["quote"] not in rows[0][3]:
                raise ReviewRequired("citation quote is not an exact substring of source %r" % citation["source_id"])
        return decision_ids

    # ---- list_actions
    def list_actions(self, commitment_id):
        if not self.client.read(load_query("action_commitment"), {"id": commitment_id}):
            raise NotFound("commitment %r not found" % commitment_id)
        rows = self.client.read(load_query("action_list"), {"id": commitment_id})
        actions = [{"id": r[0], "commitment_id": commitment_id, "kind": r[1], "assignee_id": r[2],
                    "body": r[3], "citations": json.loads(r[4]), "based_on_decision_ids": sorted(r[8]),
                    "status": r[5], "evidence_version": r[6], "created_at": r[7]} for r in rows]
        return {"evidence_version": self.current_version(), "actions": actions}


def _confirm_hash(proposal, source, expected_version):
    payload = {"proposal": {k: v for k, v in proposal.items() if v is not None},
               "source": source, "expected_version": expected_version}
    return _sha(_canonical(payload))


def _sha256_body(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
