"""Decision extraction module for Ripple.

Extracts structured decision proposals from unstructured engineering notes,
validates against graph candidates, enforces server-owned effective_at timestamps,
and flags requests requiring human review.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from backend.app.ai.prompts.extraction_prompt import (
    EXTRACTION_SYSTEM_PROMPT,
    RawExtractedProposal,
    build_extraction_prompt,
)
from backend.app.ai.provider import (
    AIProviderError,
    ExtractionValidationError,
    LLMProvider,
    ReviewRequiredError,
)
from backend.app.graph.timeutil import end_of_day_ms
from backend.app.schemas import DecisionProposal


CUSTOM_EFFECTIVE_RE = re.compile(
    r"\b(effective\s+retroactively|retroactive\s+to|effective\s+as\s+of\s+yesterday|"
    r"effective\s+next\s+week|effective\s+tomorrow|effective\s+from\s+\d{1,2}|"
    r"decision\s+effective\s+at|cutover\s+at\s+6\s*pm|effective\s+time\s+is)\b",
    re.IGNORECASE,
)

YEAR_CHECK_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
OWNERSHIP_CHANGE_RE = re.compile(
    r"\b(reassign(?:ed|ing)?\s+owner|transferred\s+ownership|new\s+owner\s+is|"
    r"replacing\s+owner|owner\s+changed\s+to)\b",
    re.IGNORECASE,
)

DATE_EXPRESSION_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2}(?:,\s*\d{4}|\s+\d{4})?\b|"
    r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:\s+\d{4}|,\s*\d{4})?\b|"
    r"\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


def _check_conflicting_dates_in_text(text: str) -> None:
    """Check if note expresses a timeline reversal (e.g. moves from later date to earlier date)."""
    moves_match = re.search(
        r"moves\s+from\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+to\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})",
        text,
        re.IGNORECASE,
    )
    if moves_match:
        from_str, to_str = moves_match.group(1), moves_match.group(2)
        try:
            d_from = datetime.strptime(from_str.strip(), "%B %d, %Y")
            d_to = datetime.strptime(to_str.strip(), "%B %d, %Y")
            if d_to < d_from:
                raise ReviewRequiredError(
                    reason=f"conflicting_dates: proposed delivery date ({to_str}) is earlier than current milestone ({from_str})",
                    field="delivery_date",
                )
        except ValueError:
            pass


def _verify_date_in_text(date_iso: str, dt_obj: datetime, text: str) -> None:
    """Verify that the extracted delivery date actually appears verbatim in the note."""
    day = dt_obj.strftime("%d")
    day_no_zero = day.lstrip("0")
    month_name = dt_obj.strftime("%B")
    month_abbr = dt_obj.strftime("%b")
    year = dt_obj.strftime("%Y")

    formatted_variants = [
        date_iso,
        f"{month_name} {day}, {year}",
        f"{month_name} {day_no_zero}, {year}",
        f"{month_name} {day} {year}",
        f"{month_name} {day_no_zero} {year}",
        f"{month_abbr} {day}, {year}",
        f"{month_abbr} {day_no_zero}, {year}",
        f"{month_abbr} {day} {year}",
        f"{month_abbr} {day_no_zero} {year}",
        f"{day} {month_name} {year}",
        f"{day_no_zero} {month_name} {year}",
        f"{day} {month_abbr} {year}",
        f"{day_no_zero} {month_abbr} {year}",
    ]

    found = any(v.lower() in text.lower() for v in formatted_variants)
    if not found:
        raise ReviewRequiredError(
            reason=f"unsupported_date: extracted delivery date '{date_iso}' does not appear in source note text",
            field="delivery_date",
        )


def _parse_delivery_date(date_str: str, text: str) -> int:
    """Parse delivery date string into end-of-day IST timestamp in UTC epoch ms.

    Requires an explicit 4-digit year associated with the date in the source note.
    """
    date_str = date_str.strip()
    dt_obj: datetime | None = None
    iso_date: str = ""

    # Try ISO YYYY-MM-DD
    match = re.search(r"^(\d{4})-(\d{2})-(\d{2})$", date_str)
    if match:
        iso_date = match.group(0)
        try:
            dt_obj = datetime.strptime(iso_date, "%Y-%m-%d")
        except ValueError:
            pass

    # Try textual formats
    if not dt_obj:
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
            try:
                dt_obj = datetime.strptime(date_str, fmt)
                iso_date = dt_obj.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    if not dt_obj or not iso_date:
        raise ReviewRequiredError(
            reason=f"ambiguous_delivery_date: could not parse delivery date '{date_str}'",
            field="delivery_date",
        )

    # Server check: verify that the note text has an explicit 4-digit year
    if not YEAR_CHECK_RE.search(text):
        raise ReviewRequiredError(
            reason="missing_or_ambiguous_year: delivery date requires explicit 4-digit year in source note (e.g. 2026)",
            field="delivery_date",
        )

    # Check for dates in note missing year
    all_date_matches = DATE_EXPRESSION_RE.findall(text)
    for dm in all_date_matches:
        if not YEAR_CHECK_RE.search(dm):
            raise ReviewRequiredError(
                reason=f"missing_or_ambiguous_year: date expression '{dm}' lacks explicit 4-digit year",
                field="delivery_date",
            )

    # Server check: verify that this date actually appears in the text!
    _verify_date_in_text(iso_date, dt_obj, text)

    return end_of_day_ms(iso_date)


def _match_work_item(name_or_id: str, candidates: dict[str, Any]) -> str:
    """Resolve work item from candidates list. Preserves ambiguity."""
    name_clean = name_or_id.strip().lower()
    work_items = candidates.get("work_items", [])
    matched_ids: set[str] = set()

    for item in work_items:
        if isinstance(item, dict):
            iid = item.get("id", "")
            iname = item.get("name", "").lower()
            aliases = [a.lower() for a in item.get("aliases", [])]
            if iid.lower() == name_clean or iname == name_clean or name_clean in aliases:
                matched_ids.add(iid)
        elif isinstance(item, str) and item.lower() == name_clean:
            matched_ids.add(item)

    if len(matched_ids) > 1:
        raise ReviewRequiredError(
            reason=f"ambiguous_entity: multiple work items match '{name_or_id}': {sorted(matched_ids)}",
            field="work_item_id",
        )
    if len(matched_ids) == 1:
        return next(iter(matched_ids))

    # Fallback to substring matching if query has substance
    if len(name_clean) >= 4 and name_clean not in ("service", "item", "engine", "feature"):
        for item in work_items:
            if isinstance(item, dict):
                iname = item.get("name", "").lower()
                if name_clean in iname:
                    matched_ids.add(item.get("id", ""))

    if len(matched_ids) > 1:
        raise ReviewRequiredError(
            reason=f"ambiguous_entity: multiple work items match '{name_or_id}': {sorted(matched_ids)}",
            field="work_item_id",
        )
    if len(matched_ids) == 1:
        return next(iter(matched_ids))

    raise ReviewRequiredError(
        reason=f"unknown_entity: work item '{name_or_id}' does not match candidate graph entities",
        field="work_item_id",
    )


def _match_owner(name_or_id: str, work_item_id: str, candidates: dict[str, Any]) -> str:
    """Resolve owner from candidates list and verify against known component owner."""
    name_clean = name_or_id.strip().lower()
    if not name_clean:
        raise ReviewRequiredError(
            reason="unknown_entity: empty owner name provided",
            field="owner_id",
        )

    people = candidates.get("people", [])
    matched_ids: set[str] = set()

    for person in people:
        if isinstance(person, dict):
            pid = person.get("id", "")
            pname = person.get("name", "").lower()
            aliases = [a.lower() for a in person.get("aliases", [])]
            if pid.lower() == name_clean or pname == name_clean or name_clean in aliases:
                matched_ids.add(pid)
                continue
            first_name = pname.split()[0] if pname.split() else ""
            if first_name and first_name == name_clean:
                matched_ids.add(pid)
        elif isinstance(person, str) and person.lower() == name_clean:
            matched_ids.add(person)

    if len(matched_ids) > 1:
        raise ReviewRequiredError(
            reason=f"ambiguous_entity: multiple people match owner '{name_or_id}': {sorted(matched_ids)}",
            field="owner_id",
        )
    if not matched_ids:
        raise ReviewRequiredError(
            reason=f"unknown_entity: owner '{name_or_id}' does not match known people in graph",
            field="owner_id",
        )

    matched_person_id = next(iter(matched_ids))

    # Ownership validation: verify if this matches the known owner for the work item
    known_owners = candidates.get("work_item_owners", {})
    if work_item_id in known_owners:
        expected_owner_id = known_owners[work_item_id]
        if matched_person_id != expected_owner_id:
            raise ReviewRequiredError(
                reason=(
                    f"ownership_reassignment_unsupported: note assigns owner '{matched_person_id}', "
                    f"but known recorded owner for '{work_item_id}' is '{expected_owner_id}'. "
                    f"Ownership reassignment requires separate approval."
                ),
                field="owner_id",
            )

    return matched_person_id


def _match_supersedes(
    decision_ref: str | None,
    work_item_id: str,
    candidates: dict[str, Any],
) -> str | None:
    """Resolve supersedes decision canonical ID against candidate decisions."""
    if not decision_ref:
        return None

    ref_clean = decision_ref.strip().upper()
    decisions = candidates.get("decisions", [])
    matched_ids: set[str] = set()

    for dec in decisions:
        if isinstance(dec, dict):
            did = dec.get("id", "").upper()
            if did == ref_clean:
                dec_wi = dec.get("work_item_id") or dec.get("revises_work_item_id")
                if dec_wi and dec_wi != work_item_id:
                    raise ReviewRequiredError(
                        reason=f"superseded_decision_mismatch: decision '{dec.get('id')}' belongs to '{dec_wi}', not '{work_item_id}'",
                        field="supersedes_id",
                    )
                matched_ids.add(dec.get("id", ""))
        elif isinstance(dec, str) and dec.upper() == ref_clean:
            matched_ids.add(dec)

    if len(matched_ids) > 1:
        raise ReviewRequiredError(
            reason=f"ambiguous_entity: multiple decisions match '{decision_ref}': {sorted(matched_ids)}",
            field="supersedes_id",
        )
    if len(matched_ids) == 1:
        return next(iter(matched_ids))

    raise ReviewRequiredError(
        reason=f"unknown_entity: superseded decision '{decision_ref}' not found in candidate graph decisions for work item '{work_item_id}'",
        field="supersedes_id",
    )


async def extract_decision(
    text: str,
    candidates: dict[str, Any],
    source_id: str,
    now: int,
    provider: LLMProvider | None = None,
) -> DecisionProposal:
    """Extract, validate, and normalize an engineering decision proposal.

    Args:
        text: Unstructured engineering note or ticket text.
        candidates: Graph entities (work_items, people, decisions) for candidate resolution.
        source_id: Server-assigned Source ID.
        now: Pavan's preview_created_at timestamp (UTC epoch ms). The proposal's
             effective_at MUST be set to this value; it is never selected by the model.
        provider: LLM provider instance. Required.

    Returns:
        Validated DecisionProposal with effective_at set to `now`.

    Raises:
        AIProviderError: If provider is not provided or live AI fails.
        ReviewRequiredError: If note requires human review.
        ExtractionValidationError: If extracted quote is not an exact verbatim substring.
    """
    if provider is None:
        raise AIProviderError(
            "An LLMProvider is required for extract_decision. "
            "In production, configure LLM_API_KEY. In tests, pass a DeterministicTestDouble."
        )

    # 1. Pre-validation checks against effective-time overrides and ownership changes in text
    if CUSTOM_EFFECTIVE_RE.search(text):
        raise ReviewRequiredError(
            reason="custom_effective_time_unsupported: explicit request for custom historical or future decision-effective time is not supported for live updates",
            field="effective_at",
        )

    if OWNERSHIP_CHANGE_RE.search(text):
        raise ReviewRequiredError(
            reason="ownership_reassignment_unsupported: ownership reassignment requires separate governance approval",
            field="owner_id",
        )

    # Cross-check text directly for conflicting timeline reversals
    _check_conflicting_dates_in_text(text)

    # 2. Call LLM for structured extraction
    prompt = build_extraction_prompt(text, candidates)
    try:
        raw: RawExtractedProposal = await provider.generate_structured(
            prompt=prompt,
            schema=RawExtractedProposal,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
        )
    except AIProviderError:
        raise
    except Exception as exc:
        raise AIProviderError(f"Unexpected error during model extraction: {exc}") from exc

    # 3. Check model-detected review flags
    if raw.custom_effective_time_requested:
        raise ReviewRequiredError(
            reason="custom_effective_time_unsupported: note explicitly requested custom decision-effective time",
            field="effective_at",
        )
    if raw.ownership_reassigned:
        raise ReviewRequiredError(
            reason="ownership_reassignment_unsupported: note proposed reassignment of component ownership",
            field="owner_id",
        )
    if raw.has_ambiguous_or_missing_year:
        raise ReviewRequiredError(
            reason="missing_or_ambiguous_year: delivery date lacks explicit 4-digit year",
            field="delivery_date",
        )
    if raw.has_conflicting_dates:
        raise ReviewRequiredError(
            reason="conflicting_dates: contradictory delivery dates found in note",
            field="delivery_date",
        )

    # 4. Server-side quote verification: MUST be exact verbatim substring! No silent line substitution.
    quote = raw.evidence_quote.strip()
    if not quote or quote not in text:
        raise ExtractionValidationError(
            f"Extracted quote '{quote}' is not an exact verbatim substring of source text"
        )

    # 5. Resolve entities against candidates
    work_item_id = _match_work_item(raw.work_item_name_or_id, candidates)
    owner_id = _match_owner(raw.owner_name_or_id, work_item_id, candidates)
    supersedes_id = _match_supersedes(raw.supersedes_decision_id, work_item_id, candidates)

    # 6. Parse and verify delivery date
    available_at = _parse_delivery_date(raw.delivery_date, text)

    return DecisionProposal(
        work_item_id=work_item_id,
        available_at=available_at,
        effective_at=now,  # Supplied preview creation time! Never model-selected.
        supersedes_id=supersedes_id,
        owner_id=owner_id,
        evidence_quote=quote,
    )
