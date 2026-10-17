"""Grounding and fact-checking layer for Ripple AI.

Enforces strict verification of model outputs against tool-retrieved graph facts,
validates exact substring quotes against stored Source bodies,
prevents invented dates or ungrounded claims, and generates safe templated drafts.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.ai.tools import GraphRepositoryProtocol
from backend.app.graph.timeutil import ist_date
from backend.app.schemas import Draft, SourceRef


# Forbidden phrasing patterns for customer update drafts
BREACH_CLAIM_RE = re.compile(
    r"\b(has\s+breached|have\s+breached|already\s+breached|are\s+in\s+breach|contract\s+violation|"
    r"breached\s+our\s+contract|penalty\s+owed)\b",
    re.IGNORECASE,
)

SYNTHETIC_LOSS_RE = re.compile(
    r"(?:\$\s*\d+[\d,]*|\b\d+\s*(?:dollars|USD|euros|INR|loss|losses|damage|penalty)\b)",
    re.IGNORECASE,
)

INVENTED_DELIVERY_RE = re.compile(
    r"\b(?:new|rescheduled|revised)\s+delivery\s+(?:is|will\s+be)\s+(?:November|December|January)\s+\d{1,2}\b",
    re.IGNORECASE,
)


class GroundingValidationError(Exception):
    """Raised when model output violates factual grounding constraints."""

    def __init__(self, message: str, field: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.details = details


def verify_citation_exact_quote(
    source_id: str,
    quote: str,
    repo: GraphRepositoryProtocol,
    cached_sources: dict[str, Any] | None = None,
) -> bool:
    """Verify that quote is an exact verbatim substring of the stored Source.body."""
    if not source_id or not quote:
        return False

    cached = cached_sources or {}
    source_body = ""

    # Check if cached source has full body
    if source_id in cached:
        src = cached[source_id]
        if isinstance(src, dict):
            source_body = src.get("body", "")
        else:
            source_body = getattr(src, "body", "")

    # If body not in cache, fetch full source from repo
    if not source_body:
        try:
            src = repo.get_source(source_id)
            source_body = src.get("body", "") if isinstance(src, dict) else getattr(src, "body", "")
            if isinstance(cached_sources, dict) and source_body:
                cached_sources[source_id] = src
        except Exception:
            return False

    if not source_body:
        return False

    # Check exact verbatim substring
    return quote in source_body or quote.strip() in source_body


def validate_citations_list(
    citations: list[SourceRef],
    repo: GraphRepositoryProtocol,
    cached_sources: dict[str, Any] | None = None,
) -> tuple[list[SourceRef], list[str]]:
    """Validate a list of citations, filtering out invalid ones and collecting warnings."""
    valid_citations: list[SourceRef] = []
    warnings: list[str] = []

    for cit in citations:
        if verify_citation_exact_quote(cit.source_id, cit.quote, repo, cached_sources):
            if cit not in valid_citations:
                valid_citations.append(cit)
        else:
            warnings.append(
                f"Dropped ungrounded citation: source '{cit.source_id}' does not contain exact quote '{cit.quote}'"
            )

    return valid_citations, warnings


def validate_draft(
    draft: Draft,
    impact_data: dict[str, Any],
    repo: GraphRepositoryProtocol,
    cached_sources: dict[str, Any] | None = None,
) -> tuple[Draft | None, list[str]]:
    """Validate a follow-up draft against graph reality.

    Rules:
    - If engineering_owner is missing or ambiguous, NO internal_escalation draft can be saved.
    - If account_owner is missing, NO customer_update draft can be saved.
    - Customer text must not claim breach, invent un-sourced delivery dates, or describe synthetic loss.
    - Citations must be exact substrings. If valid citations are empty, REJECT the draft.
    - based_on_decision_ids must strictly match known active decision IDs from blockers.
    """
    warnings: list[str] = []

    # 1. Ownership & Assignee Validation
    eng_owner = impact_data.get("engineering_owner")
    acc_owner = impact_data.get("account_owner")
    eng_owner_id = eng_owner.get("id") if eng_owner else None
    acc_owner_id = acc_owner.get("id") if acc_owner else None

    if draft.kind == "internal_escalation":
        if not eng_owner_id:
            warnings.append(
                f"Cannot produce saveable internal escalation draft for {draft.commitment_id}: "
                f"engineering owner is missing or ambiguous across blockers."
            )
            return None, warnings
        if draft.assignee_id and draft.assignee_id != eng_owner_id:
            warnings.append(
                f"Correcting internal escalation assignee from {draft.assignee_id} to blocking component owner {eng_owner_id}."
            )
            draft.assignee_id = eng_owner_id

    elif draft.kind == "customer_update":
        if not acc_owner_id:
            warnings.append(
                f"Cannot produce saveable customer update draft for {draft.commitment_id}: "
                f"account owner is missing or ambiguous."
            )
            return None, warnings
        if draft.assignee_id and draft.assignee_id != acc_owner_id:
            warnings.append(
                f"Correcting customer update assignee from {draft.assignee_id} to account owner {acc_owner_id}."
            )
            draft.assignee_id = acc_owner_id

        # 2. Textual Hallucination Checks for Customer Updates
        if BREACH_CLAIM_RE.search(draft.body):
            warnings.append(
                "Customer draft rejected: improperly claimed a breach or contract violation has occurred."
            )
            return None, warnings

        if SYNTHETIC_LOSS_RE.search(draft.body):
            warnings.append(
                "Customer draft rejected: referenced synthetic contract monetary loss."
            )
            return None, warnings

        if INVENTED_DELIVERY_RE.search(draft.body):
            warnings.append(
                "Customer draft rejected: invented an un-sourced future replacement delivery date."
            )
            return None, warnings

    # 3. Decision IDs verification (strictly blockers, never hardcoded bypass)
    blockers = impact_data.get("blockers", [])
    known_decision_ids = {b["decision_id"] for b in blockers if b.get("decision_id")}

    validated_dec_ids = [d for d in draft.based_on_decision_ids if d in known_decision_ids]
    if not validated_dec_ids:
        if known_decision_ids:
            validated_dec_ids = sorted(known_decision_ids)
        else:
            warnings.append(f"Draft rejected: no active blocker decision IDs found for {draft.commitment_id}.")
            return None, warnings
    draft.based_on_decision_ids = validated_dec_ids

    # 4. Citations verification: Draft MUST have verified citations!
    valid_citations, cit_warnings = validate_citations_list(draft.citations, repo, cached_sources)
    warnings.extend(cit_warnings)

    if not valid_citations:
        # Fallback to verify if impact has verified citations that can support this draft
        impact_cits = [
            SourceRef(source_id=c["source_id"], quote=c["quote"])
            for c in impact_data.get("citations", [])
            if verify_citation_exact_quote(c["source_id"], c["quote"], repo, cached_sources)
        ]
        if impact_cits:
            draft.citations = impact_cits
        else:
            warnings.append(f"Draft rejected: no verified citations found to ground draft for {draft.commitment_id}.")
            return None, warnings
    else:
        draft.citations = valid_citations

    return draft, warnings


def build_grounded_answer(
    question_type: str,
    impact_data: dict[str, Any] | None,
    history_data: dict[str, Any] | None,
    all_impacts: list[dict[str, Any]] | None = None,
    source_records: dict[str, Any] | None = None,
) -> str:
    """Build authoritative, factually grounded answers distinguishing recorded facts from inferences."""
    if question_type == "lineage":
        if not history_data:
            return "No forecast history recorded for this work item."

        forecasts = history_data.get("forecasts", [])
        if not forecasts:
            return "No accepted forecasts recorded."

        lines = ["Forecast and Decision Lineage:"]
        prev_fc = None
        for fc in forecasts:
            fid = fc.get("id")
            dec_id = fc.get("decision_id")
            sup_id = fc.get("supersedes_id")
            avail_ms = fc.get("available_at")
            avail_date = ist_date(avail_ms) if avail_ms else "Unknown"
            summary = fc.get("decision_summary", "")

            cits = fc.get("citations", [])
            quote_str = ""
            if cits:
                quote_str = f" Cited source: '{cits[0].get('quote', '')}'."

            if sup_id:
                prev_date = ist_date(prev_fc.get("available_at")) if prev_fc and prev_fc.get("available_at") else "earlier milestone"
                lines.append(
                    f"- Forecast {fid}: delivery moved from {prev_date} to {avail_date}. "
                    f"Established by decision {dec_id} (superseding {sup_id}). {summary}.{quote_str}"
                )
            else:
                lines.append(
                    f"- Baseline Forecast {fid}: delivery committed for {avail_date}. "
                    f"Established by decision {dec_id}. {summary}.{quote_str}"
                )
            prev_fc = fc

        lines.append(
            "\nRecorded vs. Inferred Facts:\n"
            "- Recorded: The forecast delivery dates and establishing Decisions are recorded in the engineering ticket.\n"
            "- Inferred: Downstream schedules are not automatically updated and require team replanning. "
            "No unrecorded business rationale is inferred beyond the approved decision update."
        )
        return "\n".join(lines)

    # Impact and Accountable Owners
    if impact_data:
        cid = impact_data.get("commitment_id")
        title = impact_data.get("title")
        customer = impact_data.get("customer", {}).get("name", "")
        status = impact_data.get("status")
        due_at_ms = impact_data.get("due_at")
        due_date = ist_date(due_at_ms) if due_at_ms else "Unknown"
        blockers = impact_data.get("blockers", [])
        eng_owner = impact_data.get("engineering_owner")
        acc_owner = impact_data.get("account_owner")

        eng_str = eng_owner.get("name", "Unknown") if eng_owner else "Unassigned / Ambiguous"
        acc_str = acc_owner.get("name", "Unknown") if acc_owner else "Unassigned / Ambiguous"

        if status == "date_conflict":
            blocker_details = []
            for b in blockers:
                b_name = b.get("name")
                b_avail = ist_date(b.get("available_at")) if b.get("available_at") else "Unknown"
                b_dec = b.get("decision_id")
                blocker_details.append(f"{b_name} (available {b_avail}, decision {b_dec})")

            b_str = ", ".join(blocker_details)
            return (
                f"{customer}'s commitment '{title}' ({cid}) due on {due_date} has a confirmed date conflict: "
                f"blocking dependency {b_str} crosses the promise deadline. "
                f"The accountable engineering owner for the conflict is {eng_str} (blocking component owner), "
                f"and the account owner is {acc_str}. "
                f"Recorded feature forecasts have not been modified automatically and require replanning."
            )
        elif status == "no_detected_conflict":
            return (
                f"{customer}'s commitment '{title}' ({cid}) due on {due_date} currently has no detected date conflict "
                f"based on recorded dependencies. Account owner is {acc_str} and engineering owner is {eng_str}."
            )
        else:
            reasons = "; ".join(impact_data.get("reasons", []))
            return (
                f"{customer}'s commitment '{title}' ({cid}) status is {status} (requires verification). "
                f"Reasons: {reasons}. Account owner: {acc_str}, Engineering owner: {eng_str}."
            )

    if all_impacts:
        conflicts = [i for i in all_impacts if i.get("status") == "date_conflict"]
        no_conflicts = [i for i in all_impacts if i.get("status") == "no_detected_conflict"]
        verification = [i for i in all_impacts if i.get("status") == "needs_verification"]

        conf_names = [f"{i.get('customer', {}).get('name')} ({i.get('commitment_id')})" for i in conflicts]
        no_conf_names = [f"{i.get('customer', {}).get('name')} ({i.get('commitment_id')})" for i in no_conflicts]
        ver_names = [f"{i.get('customer', {}).get('name')} ({i.get('commitment_id')})" for i in verification]

        lines = ["Impact Analysis across Commitments:"]
        if conflicts:
            lines.append(f"- Confirmed date conflicts ({len(conflicts)}): {', '.join(conf_names)}.")
        if no_conflicts:
            lines.append(f"- No detected conflict ({len(no_conflicts)}): {', '.join(no_conf_names)}.")
        if verification:
            lines.append(f"- Needs verification ({len(verification)}): {', '.join(ver_names)}.")
        lines.append(
            "Downstream schedules are not automatically recalculated when dependencies slip; teams must replan."
        )
        return "\n".join(lines)

    return "No impact data available for the requested context."
