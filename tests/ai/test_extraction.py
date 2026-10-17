"""Unit tests for decision extraction, validation, and review triggers."""

import pytest

from backend.app.ai.extraction import (
    extract_decision,
)
from backend.app.ai.prompts.extraction_prompt import RawExtractedProposal
from backend.app.ai.provider import (
    AIProviderError,
    DeterministicTestDouble,
    ExtractionValidationError,
    ProviderTimeoutError,
    ReviewRequiredError,
)
from backend.app.graph.timeutil import end_of_day_ms

CANDIDATES = {
    "work_items": [
        {"id": "wi_permissions", "name": "Permissions Service", "aliases": ["permissions", "core permissions"]},
        {"id": "wi_identity_migration", "name": "Identity Migration Service", "aliases": ["identity migration"]},
        {"id": "wi_sso", "name": "Single Sign-On", "aliases": ["sso"]},
        {"id": "wi_audit", "name": "Audit Logging", "aliases": ["audit"]},
    ],
    "people": [
        {"id": "person_priya", "name": "Priya Sharma", "aliases": ["priya"]},
        {"id": "person_lena", "name": "Lena Torres", "aliases": ["lena"]},
        {"id": "person_omar", "name": "Omar Farooq", "aliases": ["omar"]},
    ],
    "work_item_owners": {
        "wi_permissions": "person_priya",
        "wi_identity_migration": "person_lena",
        "wi_sso": "person_lena",
        "wi_audit": "person_omar",
    },
    "decisions": [
        {"id": "DEC-12", "summary": "Initial permissions delivery forecast", "work_item_id": "wi_permissions"},
    ],
}

CANONICAL_NOTE = (
    "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
    "Owner: Priya. This replaces decision DEC-12."
)


def _make_canonical_double(delivery_date="2026-10-28", supersedes_id="DEC-12", owner="Priya"):
    proposal = RawExtractedProposal(
        work_item_name_or_id="permissions",
        delivery_date=delivery_date,
        supersedes_decision_id=supersedes_id,
        owner_name_or_id=owner,
        evidence_quote="Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. Owner: Priya. This replaces decision DEC-12.",
    )
    return DeterministicTestDouble(structured_responses={"Engineering Note to Extract": proposal})


@pytest.mark.asyncio
async def test_extraction_requires_provider():
    """extract_decision raises AIProviderError if provider is None."""
    with pytest.raises(AIProviderError, match="An LLMProvider is required"):
        await extract_decision(
            text=CANONICAL_NOTE,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=None,
        )


@pytest.mark.asyncio
async def test_canonical_note_extraction_success():
    """Canonical note extracts permissions service, Priya, DEC-12, and Oct 28 IST EOD."""
    server_now = 1792240151000
    expected_eod = end_of_day_ms("2026-10-28")
    assert expected_eod == 1793212199999

    double = _make_canonical_double()
    proposal = await extract_decision(
        text=CANONICAL_NOTE,
        candidates=CANDIDATES,
        source_id="src_ticket_123",
        now=server_now,
        provider=double,
    )

    assert proposal.work_item_id == "wi_permissions"
    assert proposal.owner_id == "person_priya"
    assert proposal.supersedes_id == "DEC-12"
    assert proposal.available_at == expected_eod
    # Server owns effective_at: must match supplied 'now' timestamp, not delivery date or model selection
    assert proposal.effective_at == server_now
    assert proposal.effective_at != proposal.available_at
    assert proposal.evidence_quote in CANONICAL_NOTE


@pytest.mark.asyncio
async def test_different_delivery_date_extraction():
    """Validation works for a different valid future delivery date present in the note."""
    server_now = 1792240151000
    different_note = (
        "Approved: permissions service delivery moves from October 21, 2026 to November 10, 2026. "
        "Owner: Priya. This replaces decision DEC-12."
    )
    expected_eod = end_of_day_ms("2026-11-10")

    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id="permissions",
                delivery_date="2026-11-10",
                supersedes_decision_id="DEC-12",
                owner_name_or_id="Priya",
                evidence_quote="Approved: permissions service delivery moves from October 21, 2026 to November 10, 2026. Owner: Priya. This replaces decision DEC-12.",
            )
        }
    )

    proposal = await extract_decision(
        text=different_note,
        candidates=CANDIDATES,
        source_id="src_ticket_456",
        now=server_now,
        provider=double,
    )

    assert proposal.work_item_id == "wi_permissions"
    assert proposal.available_at == expected_eod
    assert proposal.effective_at == server_now
    assert proposal.supersedes_id == "DEC-12"


@pytest.mark.asyncio
async def test_extracted_date_must_appear_in_source_note():
    """If the model hallucinates a date not in the source note, extraction rejects it."""
    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id="permissions",
                delivery_date="2026-12-25",  # Not in CANONICAL_NOTE!
                supersedes_decision_id="DEC-12",
                owner_name_or_id="Priya",
                evidence_quote=CANONICAL_NOTE,
            )
        }
    )
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=CANONICAL_NOTE,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "unsupported_date" in exc_info.value.reason


@pytest.mark.asyncio
async def test_quote_must_be_verbatim_substring():
    """If extracted quote is not an exact substring, raises ExtractionValidationError."""
    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id="permissions",
                delivery_date="2026-10-28",
                supersedes_decision_id="DEC-12",
                owner_name_or_id="Priya",
                evidence_quote="Paraphrased permissions delivery was moved",  # Not in CANONICAL_NOTE!
            )
        }
    )
    with pytest.raises(ExtractionValidationError) as exc_info:
        await extract_decision(
            text=CANONICAL_NOTE,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "not an exact verbatim substring" in str(exc_info.value)


@pytest.mark.asyncio
async def test_custom_effective_time_rejected_for_review():
    """Notes requesting explicit retroactive or future decision effective times require review."""
    retro_note = (
        "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
        "Owner: Priya. This decision is effective retroactively from October 1."
    )
    double = _make_canonical_double()
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=retro_note,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "custom_effective_time_unsupported" in exc_info.value.reason


@pytest.mark.asyncio
async def test_missing_or_ambiguous_year_rejected_for_review():
    """Dates without explicit 4-digit years require review."""
    ambiguous_year_note = (
        "Approved: permissions service delivery moves from October 21 to October 28. "
        "Owner: Priya. This replaces decision DEC-12."
    )
    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id="permissions",
                delivery_date="2026-10-28",
                supersedes_decision_id="DEC-12",
                owner_name_or_id="Priya",
                evidence_quote=ambiguous_year_note,
                has_ambiguous_or_missing_year=True,
            )
        }
    )
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=ambiguous_year_note,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "missing_or_ambiguous_year" in exc_info.value.reason


@pytest.mark.asyncio
async def test_ownership_reassignment_rejected_for_review():
    """Attempting to assign component ownership to an unrecorded owner requires review."""
    reassigned_note = (
        "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
        "Owner: Lena. This replaces decision DEC-12."
    )
    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": RawExtractedProposal(
                work_item_name_or_id="permissions",
                delivery_date="2026-10-28",
                supersedes_decision_id="DEC-12",
                owner_name_or_id="Lena",
                evidence_quote=reassigned_note,
            )
        }
    )
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=reassigned_note,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "ownership_reassignment_unsupported" in exc_info.value.reason


@pytest.mark.asyncio
async def test_entity_ambiguity_triggers_review():
    """If a work item or owner name matches multiple candidates, review is required."""
    ambiguous_candidates = {
        "work_items": [
            {"id": "wi_perm_1", "name": "Permissions Service v1", "aliases": ["permissions"]},
            {"id": "wi_perm_2", "name": "Permissions Service v2", "aliases": ["permissions"]},
        ],
        "people": CANDIDATES["people"],
        "decisions": CANDIDATES["decisions"],
    }
    double = _make_canonical_double()
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=CANONICAL_NOTE,
            candidates=ambiguous_candidates,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "ambiguous_entity" in exc_info.value.reason


@pytest.mark.asyncio
async def test_conflicting_dates_rejected_for_review():
    """Moving delivery backward from a later milestone raises conflicting_dates review error."""
    conflict_note = (
        "Approved: permissions service delivery moves from October 28, 2026 to October 21, 2026. "
        "Owner: Priya. This replaces decision DEC-12."
    )
    double = _make_canonical_double()
    with pytest.raises(ReviewRequiredError) as exc_info:
        await extract_decision(
            text=conflict_note,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=double,
        )
    assert "conflicting_dates" in exc_info.value.reason


@pytest.mark.asyncio
async def test_provider_timeout_propagates_honestly():
    """Provider timeouts are never silently hidden with test double successes."""
    timeout_double = DeterministicTestDouble(force_timeout=True)
    with pytest.raises(ProviderTimeoutError):
        await extract_decision(
            text=CANONICAL_NOTE,
            candidates=CANDIDATES,
            source_id="src_ticket_123",
            now=1792240151000,
            provider=timeout_double,
        )
