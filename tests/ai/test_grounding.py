"""Unit tests for AI grounding validation, exact quotes, and draft constraints."""

from backend.app.ai.grounding import (
    build_grounded_answer,
    validate_citations_list,
    validate_draft,
    verify_citation_exact_quote,
)
from backend.app.schemas import Draft, SourceRef


class DummyRepo:
    def __init__(self):
        self.sources = {
            "src_real": {
                "id": "src_real",
                "body": "Approved: permissions service delivery moves from October 21, 2026 to October 28, 2026.",
            }
        }

    def get_source(self, source_id: str) -> dict:
        if source_id in self.sources:
            return self.sources[source_id]
        raise KeyError(f"Source {source_id} not found")


def test_verify_citation_exact_quote():
    """Quotes must be exact verbatim substrings of the source body, fetched on demand."""
    repo = DummyRepo()
    # Cache initially empty: fetches from repo on demand
    assert verify_citation_exact_quote(
        "src_real",
        "permissions service delivery moves from October 21, 2026 to October 28, 2026",
        repo,
        cached_sources={},
    )
    # Paraphrased or altered text fails
    assert not verify_citation_exact_quote(
        "src_real",
        "permissions delivery was postponed to late October",
        repo,
        cached_sources={},
    )
    # Unknown source fails
    assert not verify_citation_exact_quote("src_unknown", "some quote", repo)


def test_validate_citations_list_drops_hallucinations():
    """Citations that do not match stored sources are dropped with warnings."""
    repo = DummyRepo()
    cits = [
        SourceRef(source_id="src_real", quote="permissions service delivery moves"),
        SourceRef(source_id="src_fake", quote="completely made up quote"),
    ]
    valid, warnings = validate_citations_list(cits, repo)
    assert len(valid) == 1
    assert valid[0].source_id == "src_real"
    assert len(warnings) == 1
    assert "Dropped ungrounded citation" in warnings[0]


def test_internal_escalation_routes_to_blocking_engineering_owner():
    """Internal escalation drafts route to the blocking component's engineering owner."""
    repo = DummyRepo()
    impact = {
        "commitment_id": "com_acme_sso",
        "engineering_owner": {"id": "person_priya", "name": "Priya Sharma"},
        "account_owner": {"id": "person_maya", "name": "Maya Patel"},
        "blockers": [{"decision_id": "dec_live_permissions_001"}],
        "citations": [{"source_id": "src_real", "quote": "permissions service delivery moves"}],
    }
    draft = Draft(
        kind="internal_escalation",
        commitment_id="com_acme_sso",
        assignee_id="person_someone_else",
        body="Hi Priya, please coordinate on permissions replanning.",
        citations=[SourceRef(source_id="src_real", quote="permissions service delivery moves")],
        based_on_decision_ids=["dec_live_permissions_001"],
    )
    val_draft, warnings = validate_draft(draft, impact, repo)
    assert val_draft is not None
    assert val_draft.assignee_id == "person_priya"


def test_missing_engineering_owner_prevents_internal_draft():
    """Missing engineering owner returns None and does not produce a saveable draft."""
    repo = DummyRepo()
    impact = {
        "commitment_id": "com_acme_sso",
        "engineering_owner": None,
        "account_owner": {"id": "person_maya", "name": "Maya Patel"},
        "blockers": [{"decision_id": "dec_live_001"}],
        "citations": [{"source_id": "src_real", "quote": "permissions service delivery moves"}],
    }
    draft = Draft(
        kind="internal_escalation",
        commitment_id="com_acme_sso",
        assignee_id=None,
        body="Escalation text.",
        citations=[SourceRef(source_id="src_real", quote="permissions service delivery moves")],
        based_on_decision_ids=["dec_live_001"],
    )
    val_draft, warnings = validate_draft(draft, impact, repo)
    assert val_draft is None
    assert any("engineering owner is missing" in w for w in warnings)


def test_empty_citations_rejects_draft():
    """Drafts with no valid citations are rejected to ensure all drafts remain sourced."""
    repo = DummyRepo()
    impact = {
        "commitment_id": "com_acme_sso",
        "engineering_owner": {"id": "person_priya", "name": "Priya Sharma"},
        "account_owner": {"id": "person_maya", "name": "Maya Patel"},
        "blockers": [{"decision_id": "dec_live_001"}],
        "citations": [],
    }
    draft = Draft(
        kind="internal_escalation",
        commitment_id="com_acme_sso",
        assignee_id="person_priya",
        body="Hi Priya, unsourced draft.",
        citations=[],
        based_on_decision_ids=["dec_live_001"],
    )
    val_draft, warnings = validate_draft(draft, impact, repo)
    assert val_draft is None
    assert any("no verified citations" in w for w in warnings)


def test_customer_draft_rejects_breach_and_synthetic_loss_claims():
    """Customer update drafts claiming contract breach, monetary loss, or invented dates are rejected."""
    repo = DummyRepo()
    impact = {
        "commitment_id": "com_acme_sso",
        "engineering_owner": {"id": "person_priya", "name": "Priya Sharma"},
        "account_owner": {"id": "person_maya", "name": "Maya Patel"},
        "blockers": [{"decision_id": "dec_live_permissions_001"}],
        "citations": [{"source_id": "src_real", "quote": "permissions service delivery moves"}],
    }

    # Breach claim
    draft_breach = Draft(
        kind="customer_update",
        commitment_id="com_acme_sso",
        assignee_id="person_maya",
        body="We are in breach of contract due to permissions delay.",
        citations=[SourceRef(source_id="src_real", quote="permissions service delivery moves")],
        based_on_decision_ids=["dec_live_permissions_001"],
    )
    val1, w1 = validate_draft(draft_breach, impact, repo)
    assert val1 is None
    assert any("breach" in w for w in w1)

    # Synthetic loss
    draft_loss = Draft(
        kind="customer_update",
        commitment_id="com_acme_sso",
        assignee_id="person_maya",
        body="This delay caused $100,000 in customer losses.",
        citations=[SourceRef(source_id="src_real", quote="permissions service delivery moves")],
        based_on_decision_ids=["dec_live_permissions_001"],
    )
    val2, w2 = validate_draft(draft_loss, impact, repo)
    assert val2 is None
    assert any("synthetic contract monetary loss" in w for w in w2)

    # Invented future replacement delivery date
    draft_invented = Draft(
        kind="customer_update",
        commitment_id="com_acme_sso",
        assignee_id="person_maya",
        body="Our new revised delivery will be November 25.",
        citations=[SourceRef(source_id="src_real", quote="permissions service delivery moves")],
        based_on_decision_ids=["dec_live_permissions_001"],
    )
    val3, w3 = validate_draft(draft_invented, impact, repo)
    assert val3 is None
    assert any("invented an un-sourced future replacement delivery date" in w for w in w3)


def test_build_grounded_answer_states_due_date_vs_forecast():
    """Grounded impact answer states explicit promise due date vs blocker forecast date."""
    impact = {
        "commitment_id": "com_acme_sso",
        "customer": {"name": "Acme Corp"},
        "title": "Enterprise SSO",
        "due_at": 1792780199999,  # Oct 23, 2026
        "status": "date_conflict",
        "blockers": [{"name": "Permissions Service", "available_at": 1793212199999, "decision_id": "dec_live_permissions_001"}],
        "engineering_owner": {"name": "Priya Sharma"},
        "account_owner": {"name": "Maya Patel"},
    }
    answer = build_grounded_answer("impact", impact, None)
    assert "2026-10-23" in answer
    assert "2026-10-28" in answer
    assert "Priya Sharma" in answer
    assert "Maya Patel" in answer
    assert "crosses the promise deadline" in answer
    assert "replanning" in answer


def test_build_grounded_answer_lineage_details():
    """Grounded lineage answer shows milestone transition, decisions, and quotes."""
    history = {
        "forecasts": [
            {
                "id": "fc_v1",
                "available_at": 1792607399999,  # Oct 21
                "decision_id": "DEC-12",
                "supersedes_id": None,
                "decision_summary": "Initial milestone",
                "citations": [{"source_id": "src_dec12", "quote": "delivery committed for October 21"}],
            },
            {
                "id": "fc_v2",
                "available_at": 1793212199999,  # Oct 28
                "decision_id": "dec_live_permissions_001",
                "supersedes_id": "DEC-12",
                "decision_summary": "Milestone extended",
                "citations": [{"source_id": "src_ticket", "quote": "moves to October 28"}],
            },
        ]
    }
    answer = build_grounded_answer("lineage", None, history)
    assert "2026-10-21" in answer
    assert "2026-10-28" in answer
    assert "DEC-12" in answer
    assert "dec_live_permissions_001" in answer
    assert "moves to October 28" in answer
    assert "Recorded vs. Inferred Facts" in answer
