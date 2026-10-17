"""Internal IDs in agent output are replaced with display names."""
import pytest

from backend.app.ai.agent import humanize_ids, run_agent
from backend.app.ai.provider import DeterministicTestDouble
from backend.app.schemas import AgentRunRequest

NAMES = {"com_acme_sso": "Enterprise SSO", "person_priya": "Priya Raman", "wi_permissions": "Permissions service"}


def test_parenthetical_id_after_its_name_is_dropped():
    assert humanize_ids("**Priya Raman (person_priya)** owns it", NAMES) == "**Priya Raman** owns it"


def test_bare_and_backticked_ids_become_names():
    assert humanize_ids("`wi_permissions` blocks com_acme_sso", NAMES) == "Permissions service blocks Enterprise SSO"


def test_parenthetical_without_its_name_keeps_the_name():
    assert humanize_ids("The commitment (com_acme_sso) slipped", NAMES) == "The commitment (Enterprise SSO) slipped"


def test_unknown_ids_and_decision_codes_are_left_alone():
    assert humanize_ids("DEC-13 and wi_unknown", NAMES) == "DEC-13 and wi_unknown"


class ExpertsRepo:
    version = "ds:1"
    body = "[09:46] Priya: Dropping custom role templates for v1."

    def get_version(self):
        return self.version

    def get_source(self, source_id):
        return {"id": source_id, "title": "#eng-platform thread", "body": self.body}

    def resolve_entity(self, query, kind=None):
        return [{"id": "wi_permissions", "kind": "work_item", "name": "Permissions service"}]

    def get_experts(self, work_item_id):
        return {"evidence_version": self.version, "work_item_id": work_item_id, "experts": [
            {"id": "person_priya", "name": "Priya Raman", "score": 4, "reasons": [
                {"kind": "discussed", "source_id": "src_platform_chat", "quote": self.body}]}]}


@pytest.mark.asyncio
async def test_who_knows_question_uses_find_experts_and_cites_the_chat():
    req = AgentRunRequest(message="Who knows the most about the permissions service?", expected_version="ds:1")
    res = await run_agent(request=req, tools=ExpertsRepo(), provider=DeterministicTestDouble())
    assert "find_experts" in [t.tool for t in res.tool_trace]
    assert "Priya Raman" in res.answer and "person_priya" not in res.answer
    assert [c.source_id for c in res.citations] == ["src_platform_chat"]


def test_iso_dates_become_readable():
    assert humanize_ids("due on 2026-10-23", NAMES) == "due on 23 October 2026"


def test_quoted_evidence_and_timestamps_stay_verbatim():
    text = 'Priya wrote "Load tests pass 2026-09-30" at 2026-09-30 16:40, due 2026-10-23.'
    assert humanize_ids(text, NAMES) == 'Priya wrote "Load tests pass 2026-09-30" at 2026-09-30 16:40, due 23 October 2026.'


class AuditRepo(ExpertsRepo):
    def get_evidence(self, commitment_id, as_of_ms=None):
        return {"commitment_id": commitment_id, "status": "date_conflict", "citations": [],
                "blockers": [{"work_item_id": "wi_audit", "name": "Audit-log feature"}], "paths": []}

    def get_experts(self, work_item_id):
        result = super().get_experts(work_item_id)
        result["work_item_id"] = work_item_id
        return result


@pytest.mark.asyncio
async def test_scripted_expert_question_follows_the_selected_commitment():
    req = AgentRunRequest(message="Who knows the most about it?", commitment_id="com_birch_audit", expected_version="ds:1")
    res = await run_agent(request=req, tools=AuditRepo(), provider=DeterministicTestDouble())
    experts_call = next(t for t in res.tool_trace if t.tool == "find_experts")
    assert experts_call.arguments == {"work_item_id": "wi_audit"}
