"""Integration tests validating AI layer against synthetic Harbor fixtures."""

import json
from pathlib import Path
import pytest

from backend.app.ai.extraction import extract_decision
from backend.app.ai.grounding import verify_citation_exact_quote
from backend.app.ai.provider import DeterministicTestDouble
from backend.app.graph.timeutil import end_of_day_ms

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "harbor"


def load_harbor_candidates():
    with open(FIXTURES_DIR / "entities" / "work_items.json", encoding="utf-8") as f:
        work_items = json.load(f)
    with open(FIXTURES_DIR / "entities" / "people.json", encoding="utf-8") as f:
        people = json.load(f)
    with open(FIXTURES_DIR / "decisions" / "decisions.json", encoding="utf-8") as f:
        decisions = json.load(f)

    return {
        "work_items": work_items,
        "people": people,
        "decisions": decisions,
        "work_item_owners": {
            "wi_permissions": "person_priya",
            "wi_identity_migration": "person_lena",
            "wi_sso": "person_lena",
            "wi_audit": "person_omar",
            "wi_export": "person_eli",
            "wi_export_worker": "person_eli",
        },
    }


class HarborSourceRepo:
    def __init__(self):
        self.sources = {}
        sources_dir = FIXTURES_DIR / "sources"
        for md_file in sources_dir.glob("*.md"):
            source_id = md_file.stem
            self.sources[source_id] = {
                "id": source_id,
                "body": md_file.read_text(encoding="utf-8"),
            }

    def get_source(self, source_id: str) -> dict:
        if source_id in self.sources:
            return self.sources[source_id]
        raise KeyError(f"Source {source_id} not found")


@pytest.mark.asyncio
async def test_extract_canonical_note_with_harbor_fixtures():
    """Canonical note extraction resolves real Harbor entities, Priya, and DEC-12."""
    candidates = load_harbor_candidates()
    canonical_text = (
        "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026. "
        "Owner: Priya. This replaces decision DEC-12."
    )
    server_preview_time = 1792240151000
    double = DeterministicTestDouble(
        structured_responses={
            "Engineering Note to Extract": {
                "work_item_name_or_id": "Permissions Service",
                "delivery_date": "2026-10-28",
                "supersedes_decision_id": "DEC-12",
                "owner_name_or_id": "Priya",
                "evidence_quote": canonical_text,
            }
        }
    )

    proposal = await extract_decision(
        text=canonical_text,
        candidates=candidates,
        source_id="src_permissions_ticket",
        now=server_preview_time,
        provider=double,
    )

    assert proposal.work_item_id == "wi_permissions"
    assert proposal.owner_id == "person_priya"
    assert proposal.supersedes_id == "DEC-12"
    assert proposal.available_at == end_of_day_ms("2026-10-28")
    assert proposal.effective_at == server_preview_time


def test_harbor_sources_quotes_are_exact_substrings():
    """Verify that quotes referenced in harbor sources are verbatim substrings."""
    repo = HarborSourceRepo()

    # src_dec12 quote
    quote_dec12 = "Approved. The permissions service will be delivered by October 21, 2026."
    assert verify_citation_exact_quote("src_dec12", quote_dec12, repo)

    # src_acme_handoff quote
    quote_acme = "Commitment: Enterprise SSO delivered by October 23, 2026."
    assert verify_citation_exact_quote("src_acme_handoff", quote_acme, repo)

    # src_birch_handoff quote
    quote_birch = "Commitment: Audit-log feature delivered by October 26, 2026."
    assert verify_citation_exact_quote("src_birch_handoff", quote_birch, repo)

    # src_cedar_handoff quote
    quote_cedar = "Commitment: Data export delivered by October 23, 2026."
    assert verify_citation_exact_quote("src_cedar_handoff", quote_cedar, repo)
