"""Bounded tool suite for Ripple AI Agent.

Wraps Ashwin's GraphRepository to provide bounded, read-only graph queries
and fact-grounded drafting with a strict 6-call budget and structured tracing.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from backend.app.schemas import (
    Draft,
    SourceRef,
    ToolTraceItem,
)

MAX_TOOL_CALLS = 6


class GraphRepositoryProtocol(Protocol):
    """Protocol for injected repository interface (keeps AI decoupled from API/DB)."""

    def get_version(self) -> str: ...
    def get_source(self, source_id: str) -> dict[str, Any]: ...
    def get_history(self, work_item_id: str) -> dict[str, Any]: ...
    def list_impacts(self, as_of_ms: int | None) -> dict[str, Any]: ...
    def get_evidence(self, commitment_id: str, as_of_ms: int | None) -> dict[str, Any]: ...
    def get_owners(self, commitment_id: str, as_of_ms: int | None) -> dict[str, Any]: ...
    def resolve_entity(self, query: str, kind: str | None = None) -> list[dict[str, Any]]: ...


class ToolBudgetExceededError(Exception):
    """Raised when the agent attempts more than MAX_TOOL_CALLS operations."""


TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "resolve_entity",
        "description": "Resolve an entity name, ID, or alias to candidate graph entities (customers, commitments, work_items, people). Preserves ambiguity.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The name, alias, or ID to look up (e.g. 'Acme', 'permissions', 'Priya').",
                },
                "kind": {
                    "type": "STRING",
                    "description": "Optional entity kind filter: 'customer', 'commitment', 'work_item', 'person'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_impacted_commitments",
        "description": "Retrieve current statuses, blockers, version, and completeness for all commitments in the graph.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "as_of": {
                    "type": "INTEGER",
                    "description": "Optional UTC epoch ms timestamp. Defaults to current server time.",
                },
            },
        },
    },
    {
        "name": "get_evidence",
        "description": "Retrieve ordered dependency paths, blockers, status, and source citations for a specific commitment ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "commitment_id": {
                    "type": "STRING",
                    "description": "The canonical commitment ID (e.g. 'com_acme_sso').",
                },
                "as_of": {
                    "type": "INTEGER",
                    "description": "Optional UTC epoch ms timestamp.",
                },
            },
            "required": ["commitment_id"],
        },
    },
    {
        "name": "get_owners",
        "description": "Retrieve accountable engineering and account owners for a commitment. For date conflicts, returns the unique blocking component owner.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "commitment_id": {
                    "type": "STRING",
                    "description": "The canonical commitment ID (e.g. 'com_acme_sso').",
                },
                "as_of": {
                    "type": "INTEGER",
                    "description": "Optional UTC epoch ms timestamp.",
                },
            },
            "required": ["commitment_id"],
        },
    },
    {
        "name": "get_forecast_history",
        "description": "Retrieve accepted forecast versions, valid intervals, establishing decisions, and citations for a work item ID.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "work_item_id": {
                    "type": "STRING",
                    "description": "The work item ID (e.g. 'wi_permissions').",
                },
            },
            "required": ["work_item_id"],
        },
    },
    {
        "name": "get_source",
        "description": "Retrieve full source record with body, title, and timestamp by source ID to inspect exact source quotes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_id": {
                    "type": "STRING",
                    "description": "The source ID (e.g. 'src_permissions_ticket', 'src_dec12').",
                },
            },
            "required": ["source_id"],
        },
    },
    {
        "name": "draft_followup",
        "description": "Prepare a validated follow-up draft (internal_escalation or customer_update) grounded in retrieved graph evidence.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {
                    "type": "STRING",
                    "description": "'internal_escalation' or 'customer_update'.",
                },
                "commitment_id": {
                    "type": "STRING",
                    "description": "The commitment ID being addressed.",
                },
                "assignee_id": {
                    "type": "STRING",
                    "description": "The accountable person ID.",
                },
                "body": {
                    "type": "STRING",
                    "description": "The drafted message body.",
                },
                "citations": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "source_id": {"type": "STRING"},
                            "quote": {"type": "STRING"},
                        },
                        "required": ["source_id", "quote"],
                    },
                    "description": "Exact quoted evidence supporting this draft.",
                },
                "based_on_decision_ids": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Decisions establishing the active conflict or change.",
                },
            },
            "required": ["kind", "commitment_id", "assignee_id", "body", "citations", "based_on_decision_ids"],
        },
    },
]


class AgentTools:
    """Tool execution layer for Ripple AI Agent.

    Enforces maximum 6 tool calls, logs structured tool traces,
    and returns factual graph evidence.
    """

    def __init__(self, repo: GraphRepositoryProtocol, as_of: int | None = None) -> None:
        self.repo = repo
        self.as_of = as_of if as_of is not None else int(time.time() * 1000)
        self.call_count = 0
        self.trace: list[ToolTraceItem] = []
        self.accumulated_evidence: dict[str, Any] = {
            "sources": {},           # Stores full Source objects with 'body'
            "citations": [],         # Stores list of citation references {source_id, quote}
            "impacts": {},
            "histories": {},
            "entities": {},
            "owners": {},
            "drafts": [],
        }
        self.warnings: list[str] = []

    def _add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _record_call(
        self,
        tool: str,
        arguments: dict[str, Any],
        evidence_ids: list[str],
        status: str = "ok",
    ) -> None:
        self.trace.append(
            ToolTraceItem(
                tool=tool,
                arguments=arguments,
                evidence_ids=evidence_ids,
                status="ok" if status == "ok" else "error",
            )
        )

    def _check_budget(self, tool_name: str) -> None:
        if self.call_count >= MAX_TOOL_CALLS:
            self._add_warning(f"Tool budget limit ({MAX_TOOL_CALLS}) reached when calling '{tool_name}'")
            raise ToolBudgetExceededError(
                f"Agent exceeded maximum tool call budget of {MAX_TOOL_CALLS} calls."
            )
        self.call_count += 1

    def resolve_entity(self, query: str, kind: str | None = None) -> list[dict[str, Any]]:
        """Find candidate graph entities matching query, preserving ambiguity."""
        self._check_budget("resolve_entity")
        args = {"query": query, "kind": kind}
        try:
            results = self.repo.resolve_entity(query, kind=kind)
            evidence_ids = [item.get("id", "") for item in results if "id" in item]
            for item in results:
                if "id" in item:
                    self.accumulated_evidence["entities"][item["id"]] = item
            self._record_call("resolve_entity", args, evidence_ids, "ok")
            return results
        except Exception as exc:
            self._record_call("resolve_entity", args, [], "error")
            self._add_warning(f"resolve_entity failed for query '{query}': {exc}")
            raise

    def find_impacted_commitments(self, as_of: int | None = None) -> dict[str, Any]:
        """Retrieve current statuses, blockers, version, and completeness for all commitments."""
        self._check_budget("find_impacted_commitments")
        effective_as_of = as_of if as_of is not None else self.as_of
        args = {"as_of": effective_as_of}
        try:
            res = self.repo.list_impacts(effective_as_of)
            impacts = res.get("impacts", [])
            evidence_ids = [imp.get("commitment_id", "") for imp in impacts if "commitment_id" in imp]
            for imp in impacts:
                cid = imp.get("commitment_id")
                if cid:
                    self.accumulated_evidence["impacts"][cid] = imp
                    # Accumulate citations separately from sources
                    for cit in imp.get("citations", []):
                        if cit not in self.accumulated_evidence["citations"]:
                            self.accumulated_evidence["citations"].append(cit)
            self._record_call("find_impacted_commitments", args, evidence_ids, "ok")
            return res
        except Exception as exc:
            self._record_call("find_impacted_commitments", args, [], "error")
            self._add_warning(f"find_impacted_commitments failed: {exc}")
            raise

    def get_evidence(self, commitment_id: str, as_of: int | None = None) -> dict[str, Any]:
        """Retrieve ordered dependency paths, blockers, status, and source citations for a commitment."""
        self._check_budget("get_evidence")
        effective_as_of = as_of if as_of is not None else self.as_of
        args = {"commitment_id": commitment_id, "as_of": effective_as_of}
        try:
            impact = self.repo.get_evidence(commitment_id, effective_as_of)
            citations = impact.get("citations", [])
            evidence_ids = [c.get("source_id", "") for c in citations if "source_id" in c]
            self.accumulated_evidence["impacts"][commitment_id] = impact
            for cit in citations:
                if cit not in self.accumulated_evidence["citations"]:
                    self.accumulated_evidence["citations"].append(cit)
            self._record_call("get_evidence", args, evidence_ids, "ok")
            return impact
        except Exception as exc:
            self._record_call("get_evidence", args, [], "error")
            self._add_warning(f"get_evidence failed for '{commitment_id}': {exc}")
            raise

    def get_owners(self, commitment_id: str, as_of: int | None = None) -> dict[str, Any]:
        """Retrieve accountable engineering and account owners without guessing."""
        self._check_budget("get_owners")
        effective_as_of = as_of if as_of is not None else self.as_of
        args = {"commitment_id": commitment_id, "as_of": effective_as_of}
        try:
            res = self.repo.get_owners(commitment_id, effective_as_of)
            evidence_ids = []
            eng = res.get("engineering_owner")
            if eng and "id" in eng:
                evidence_ids.append(eng["id"])
            acc = res.get("account_owner")
            if acc and "id" in acc:
                evidence_ids.append(acc["id"])
            self.accumulated_evidence["owners"][commitment_id] = res
            self._record_call("get_owners", args, evidence_ids, "ok")
            return res
        except Exception as exc:
            self._record_call("get_owners", args, [], "error")
            self._add_warning(f"get_owners failed for '{commitment_id}': {exc}")
            raise

    def get_forecast_history(self, work_item_id: str) -> dict[str, Any]:
        """Retrieve forecast versions, establishing decisions, and citations for a work item."""
        self._check_budget("get_forecast_history")
        args = {"work_item_id": work_item_id}
        try:
            res = self.repo.get_history(work_item_id)
            forecasts = res.get("forecasts", [])
            evidence_ids = []
            for fc in forecasts:
                if "id" in fc:
                    evidence_ids.append(fc["id"])
                if "decision_id" in fc and fc["decision_id"]:
                    evidence_ids.append(fc["decision_id"])
                for cit in fc.get("citations", []):
                    if cit not in self.accumulated_evidence["citations"]:
                        self.accumulated_evidence["citations"].append(cit)
            self.accumulated_evidence["histories"][work_item_id] = res
            self._record_call("get_forecast_history", args, evidence_ids, "ok")
            return res
        except Exception as exc:
            self._record_call("get_forecast_history", args, [], "error")
            self._add_warning(f"get_forecast_history failed for '{work_item_id}': {exc}")
            raise

    def get_source(self, source_id: str) -> dict[str, Any]:
        """Retrieve full source record with title, body, and timestamp."""
        # Check if already fetched and cached with full body
        if source_id in self.accumulated_evidence["sources"]:
            cached = self.accumulated_evidence["sources"][source_id]
            if cached.get("body"):
                return cached

        self._check_budget("get_source")
        args = {"source_id": source_id}
        try:
            src = self.repo.get_source(source_id)
            # Store full source object with 'body'
            self.accumulated_evidence["sources"][source_id] = src
            self._record_call("get_source", args, [source_id], "ok")
            return src
        except Exception as exc:
            self._record_call("get_source", args, [source_id], "error")
            self._add_warning(f"get_source failed for '{source_id}': {exc}")
            raise

    def draft_followup(
        self,
        kind: str,
        commitment_id: str,
        assignee_id: str | None,
        body: str,
        citations: list[dict[str, str]],
        based_on_decision_ids: list[str],
    ) -> Draft:
        """Create a structured follow-up draft grounded in tool evidence."""
        args = {
            "kind": kind,
            "commitment_id": commitment_id,
            "assignee_id": assignee_id,
            "citations_count": len(citations),
            "based_on_decision_ids": based_on_decision_ids,
        }
        evidence_ids = [c["source_id"] for c in citations if "source_id" in c] + based_on_decision_ids
        self._record_call("draft_followup", args, evidence_ids, "ok")

        citation_refs = [
            SourceRef(source_id=c["source_id"], quote=c["quote"])
            for c in citations
        ]

        draft = Draft(
            kind=kind,  # type: ignore[arg-type]
            commitment_id=commitment_id,
            assignee_id=assignee_id,
            body=body,
            citations=citation_refs,
            based_on_decision_ids=based_on_decision_ids,
        )
        self.accumulated_evidence["drafts"].append(draft)
        return draft
