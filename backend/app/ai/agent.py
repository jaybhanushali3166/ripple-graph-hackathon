"""Bounded AI Agent orchestrator for Ripple.

Coordinates tool execution, budget enforcement, model generation,
and fact-checking validation across impact/owners and decision lineage questions.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from backend.app.ai.grounding import (
    build_grounded_answer,
    validate_citations_list,
    validate_draft,
    verify_citation_exact_quote,
)
from backend.app.graph.timeutil import ist_date
from backend.app.ai.prompts.agent_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from backend.app.ai.provider import (
    AIProviderError,
    AgentStepResult,
    DeterministicTestDouble,
    LLMProvider,
    ProviderTimeoutError,
    ToolCall,
)
from backend.app.ai.tools import (
    MAX_TOOL_CALLS,
    TOOL_DECLARATIONS,
    AgentTools,
    GraphRepositoryProtocol,
    ToolBudgetExceededError,
)
from backend.app.schemas import (
    AgentResponse,
    AgentRunRequest,
    Draft,
    SourceRef,
)


TOTAL_AGENT_TIMEOUT_SECONDS = 30.0

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b(?![\dT:]|\s\d{1,2}:\d{2})")
_QUOTED_RE = re.compile(r'("[^"\n]*"|“[^”\n]*”)')
_ID_RE = re.compile(r"\b(?:com|wi|person|cust|src|fc|team|dec)_[A-Za-z0-9_]+\b")


def _human_date(ms: int) -> str:
    """"28 October 2026" for an epoch-ms IST date."""
    return _iso_to_human(ist_date(ms))


def _display_names(evidence: dict[str, Any]) -> dict[str, str]:
    """Internal ID -> display name, from everything the tools retrieved this run."""
    names: dict[str, str] = {}
    for entity in evidence.get("entities", {}).values():
        if entity.get("id") and entity.get("name"):
            names[entity["id"]] = entity["name"]
    for impact in evidence.get("impacts", {}).values():
        names[impact.get("commitment_id", "")] = impact.get("title") or ""
        customer = impact.get("customer") or {}
        names[customer.get("id", "")] = customer.get("name") or ""
        for path in impact.get("paths", []):
            for node in path.get("nodes", []):
                names[node["id"]] = node["label"]
        for blocker in impact.get("blockers", []):
            names[blocker["work_item_id"]] = blocker.get("name") or ""
        for role in ("engineering_owner", "account_owner"):
            if impact.get(role):
                names[impact[role]["id"]] = impact[role]["name"]
    for owners in evidence.get("owners", {}).values():
        for role in ("engineering_owner", "account_owner"):
            if owners.get(role):
                names[owners[role]["id"]] = owners[role]["name"]
    for experts in evidence.get("experts", {}).values():
        for expert in experts.get("experts", []):
            names[expert["id"]] = expert["name"]
    for source_id, source in evidence.get("sources", {}).items():
        if source.get("title"):
            names[source_id] = source["title"]
    return {k: v for k, v in names.items() if k and v}


def humanize_ids(text: str, names: dict[str, str]) -> str:
    """Replace internal IDs the model echoed with display names.

    "Priya Raman (person_priya)" loses the parenthetical; a bare or backticked ID becomes
    its name. Unknown IDs are left alone rather than guessed. ISO dates become "23 October 2026".
    """
    if not text:
        return text

    def paren(match: re.Match) -> str:
        ident = match.group(1)
        name = names.get(ident)
        if name is None:
            return match.group(0)
        before = text[max(0, match.start() - len(name) - 6):match.start()]
        return "" if name.lower() in before.lower() else f" ({name})"

    text = re.sub(r"\s*\(\s*`?(" + _ID_RE.pattern + r")`?\s*\)", paren, text)
    text = re.sub(r"`(" + _ID_RE.pattern + r")`", lambda m: names.get(m.group(1), m.group(0)), text)
    text = _ID_RE.sub(lambda m: names.get(m.group(0), m.group(0)), text)
    # Quoted evidence stays verbatim; only the model's own prose gets readable dates.
    return "".join(part if i % 2 else _ISO_DATE_RE.sub(lambda m: _iso_to_human(m.group(0)), part)
                   for i, part in enumerate(_QUOTED_RE.split(text)))


def _iso_to_human(day: str) -> str:
    from datetime import date
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{parsed.day} {parsed:%B %Y}"


def _experts_answer(experts_data: list[dict[str, Any]], names: dict[str, str]) -> str:
    """Grounded fallback answer for who-knows-what questions."""
    lines = []
    for experts in experts_data:
        subject = names.get(experts.get("work_item_id", ""), "this work item")
        ranked = experts.get("experts", [])
        if not ranked:
            lines.append(f"No one is recorded as knowing about {subject}.")
            continue
        lines.append(f"**{ranked[0]['name']}** knows the most about {subject}.")
        for expert in ranked:
            kinds = sorted({r["kind"] for r in expert["reasons"]})
            label = {"owns": "owner", "discussed": "discussed it", "member_of": "responsible team"}
            lines.append(f"- **{expert['name']}**: " + ", ".join(label[k] for k in kinds))
    return "\n".join(lines)


class StaleEvidenceError(Exception):
    """Raised when expected_version does not match the active knowledge revision."""

    def __init__(self, expected: str, current: str) -> None:
        super().__init__(
            f"The expected evidence version '{expected}' is stale. Current knowledge version is '{current}'."
        )
        self.expected = expected
        self.current = current


def _serialize_tool_output(obj: Any) -> Any:
    """Recursively convert Pydantic models and objects to JSON-serializable primitives."""
    if hasattr(obj, "model_dump"):
        return _serialize_tool_output(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _serialize_tool_output(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_tool_output(v) for v in obj]
    return obj


def _subject_work_item(messages: list[dict[str, Any]]) -> str | None:
    """The blocking (else first required) work item from a get_evidence response in messages."""
    for m in messages:
        for fr in m.get("function_responses") or []:
            if fr.get("name") != "get_evidence" or not isinstance(fr.get("response"), dict):
                continue
            evidence = fr["response"]
            if evidence.get("blockers"):
                return evidence["blockers"][0]["work_item_id"]
            for path in evidence.get("paths", []):
                for edge in path.get("edges", []):
                    if edge.get("relation") == "REQUIRES":
                        return edge["to_id"]
    return None


def _default_tool_step_handler(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AgentStepResult:
    """Simulate realistic model tool selection for DeterministicTestDouble in tests."""
    user_msg = ""
    for m in messages:
        if m.get("role") == "user":
            user_msg = m.get("text", "")
            break

    lower = user_msg.lower()

    # Track which tools have already run by checking function responses in messages
    completed_tools: set[str] = set()
    for m in messages:
        if m.get("role") == "function":
            if "function_responses" in m:
                for fr in m["function_responses"]:
                    completed_tools.add(fr.get("name"))
            if "function_response" in m:
                completed_tools.add(m["function_response"].get("name"))

    # Step 1: Always resolve entity first if not yet done
    if "resolve_entity" not in completed_tools:
        query = "permissions"
        kind = None
        if "acme" in lower:
            query, kind = "Acme", "customer"
        elif "birch" in lower:
            query, kind = "Birch", "customer"
        elif "cedar" in lower:
            query, kind = "Cedar", "customer"
        elif "delta" in lower:
            query, kind = "Delta", "customer"
        elif "globex" in lower:
            query, kind = "Globex", "customer"
        return AgentStepResult(
            tool_calls=[ToolCall(name="resolve_entity", arguments={"query": query, "kind": kind})]
        )

    # If Globex or unknown entity was queried and returned no results
    for m in messages:
        if m.get("role") == "function":
            frs = m.get("function_responses") or ([m.get("function_response")] if m.get("function_response") else [])
            for fr in frs:
                if fr.get("name") == "resolve_entity":
                    res = fr.get("response", [])
                    if isinstance(res, dict) and "result" in res:
                        res = res["result"]
                    if not res and "globex" in lower:
                        return AgentStepResult(
                            text="Entity 'Globex' was not found in the graph. No commitments or impacts exist for this customer."
                        )

    # Expertise path: get_evidence for the selected commitment, then find_experts on its blocker
    # (or required root), so the answer is about the work behind the selected promise.
    if "who knows" in lower or "expert" in lower:
        ctx = re.search(r"\(Selected commitment context:\s*([a-zA-Z0-9_]+)\)", user_msg)
        cid = ctx.group(1) if ctx and ctx.group(1) != "None" else None
        if cid and "get_evidence" not in completed_tools:
            return AgentStepResult(tool_calls=[ToolCall(name="get_evidence", arguments={"commitment_id": cid})])
        if "find_experts" not in completed_tools:
            subject = _subject_work_item(messages) or "wi_permissions"
            return AgentStepResult(
                tool_calls=[ToolCall(name="find_experts", arguments={"work_item_id": subject})]
            )
        return AgentStepResult(text=None)

    # Lineage path: get_forecast_history -> get_source
    if "lineage" in lower or "why" in lower or "dec-12" in lower or "history" in lower:
        if "get_forecast_history" not in completed_tools:
            return AgentStepResult(
                tool_calls=[ToolCall(name="get_forecast_history", arguments={"work_item_id": "wi_permissions"})]
            )
        if "get_source" not in completed_tools:
            return AgentStepResult(
                tool_calls=[ToolCall(name="get_source", arguments={"source_id": "src_permissions_ticket"})]
            )
        return AgentStepResult(text=None)

    # Extract commitment context from user message if passed
    target_cid = "com_acme_sso"
    ctx_match = re.search(r"\(Selected commitment context:\s*([a-zA-Z0-9_]+)\)", user_msg)
    if ctx_match and ctx_match.group(1) != "None":
        target_cid = ctx_match.group(1)
    elif "birch" in lower:
        target_cid = "com_birch_audit"
    elif "cedar" in lower:
        target_cid = "com_cedar_export"
    elif "delta" in lower:
        target_cid = "com_delta_sso"

    if "get_evidence" not in completed_tools and "find_impacted_commitments" not in completed_tools:
        if "all" in lower or "what commitments" in lower:
            return AgentStepResult(tool_calls=[ToolCall(name="find_impacted_commitments", arguments={})])
        return AgentStepResult(
            tool_calls=[ToolCall(name="get_evidence", arguments={"commitment_id": target_cid})]
        )

    if "get_source" not in completed_tools:
        return AgentStepResult(
            tool_calls=[ToolCall(name="get_source", arguments={"source_id": "src_permissions_ticket"})]
        )

    return AgentStepResult(text=None)


async def _execute_agent_run(
    request: AgentRunRequest,
    tool_runner: AgentTools,
    provider: LLMProvider | None,
    now_ms: int | None,
) -> AgentResponse:
    if provider is None:
        raise AIProviderError(
            "An LLMProvider is required for run_agent. "
            "In production, configure LLM_API_KEY. In tests, pass a DeterministicTestDouble."
        )

    repo = tool_runner.repo
    current_version = repo.get_version()

    # 1. Version gate: verify expected_version matches graph state
    if request.expected_version and request.expected_version != current_version:
        raise StaleEvidenceError(expected=request.expected_version, current=current_version)

    warnings: list[str] = []
    status: str = "complete"

    effective_provider = provider
    if isinstance(effective_provider, DeterministicTestDouble) and effective_provider.tool_step_handler is None:
        effective_provider.tool_step_handler = _default_tool_step_handler

    # Tool mapping
    tool_map = {
        "resolve_entity": tool_runner.resolve_entity,
        "find_impacted_commitments": tool_runner.find_impacted_commitments,
        "get_evidence": tool_runner.get_evidence,
        "get_owners": tool_runner.get_owners,
        "get_forecast_history": tool_runner.get_forecast_history,
        "get_source": tool_runner.get_source,
        "find_experts": tool_runner.find_experts,
        "draft_followup": tool_runner.draft_followup,
    }

    # Initialize message conversation
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "text": (
                f"{request.message}\n"
                f"(Selected commitment context: {request.commitment_id or 'None'})"
            ),
        }
    ]

    answer_text: str | None = None
    iteration_count = 0
    MAX_ITERATIONS = 6
    last_step_had_tool_calls = True

    # 2. Genuine Model Tool-Calling Loop with Multi-turn Protocol & Budget Enforcement
    try:
        while iteration_count < MAX_ITERATIONS and tool_runner.call_count < MAX_TOOL_CALLS:
            iteration_count += 1
            step_result = await effective_provider.generate_tool_step(
                messages=messages,
                tools=TOOL_DECLARATIONS,
                system_prompt=AGENT_SYSTEM_PROMPT,
            )

            # If model returned text without tool calls, we're done
            if not step_result.tool_calls:
                answer_text = step_result.text
                last_step_had_tool_calls = False
                break

            # Multi-turn tool-calling protocol: append assistant/model turn with tool calls
            model_call_parts = [
                {"name": c.name, "args": c.arguments}
                for c in step_result.tool_calls
            ]
            ollama_tool_calls = [
                {"function": {"name": c.name, "arguments": c.arguments}}
                for c in step_result.tool_calls
            ]
            messages.append({
                "role": "model",
                "function_calls": model_call_parts,
                "tool_calls": ollama_tool_calls,
            })

            # Execute tool calls
            function_responses = []
            for call in step_result.tool_calls:
                if call.name not in tool_map:
                    tool_runner._add_warning(f"Model attempted unknown tool: '{call.name}'")
                    try:
                        tool_runner._check_budget(call.name)
                    except ToolBudgetExceededError:
                        status = "partial"
                    function_responses.append({
                        "name": call.name,
                        "response": {"error": f"Unknown tool '{call.name}'"},
                    })
                    continue

                if tool_runner.call_count >= MAX_TOOL_CALLS:
                    tool_runner._add_warning(f"Tool budget limit ({MAX_TOOL_CALLS}) reached.")
                    status = "partial"
                    break

                try:
                    tool_fn = tool_map[call.name]
                    # Run synchronous repo call in thread pool so asyncio.wait_for can interrupt
                    tool_output = await asyncio.to_thread(tool_fn, **call.arguments)
                except ToolBudgetExceededError:
                    status = "partial"
                    function_responses.append({
                        "name": call.name,
                        "response": {"error": "Tool call budget exceeded"},
                    })
                    break
                except Exception as exc:
                    tool_output = {"error": str(exc)}
                    tool_runner._add_warning(f"Tool {call.name} error: {exc}")

                ser_out = _serialize_tool_output(tool_output)
                resp_dict = ser_out if isinstance(ser_out, dict) else {"result": ser_out}
                function_responses.append({
                    "name": call.name,
                    "response": resp_dict,
                })

            if function_responses:
                messages.append({
                    "role": "function",
                    "function_responses": function_responses,
                })

            if status == "partial":
                break

    except ProviderTimeoutError as exc:
        tool_runner._add_warning(f"AI Provider timed out: {exc}. Returning grounded partial results.")
        status = "partial"
    except AIProviderError as exc:
        tool_runner._add_warning(f"AI Provider error: {exc}. Returning grounded partial results.")
        status = "partial"
    except Exception as exc:
        tool_runner._add_warning(f"Unexpected generation failure: {exc}")
        status = "partial"

    if last_step_had_tool_calls:
        status = "partial"
        if iteration_count >= MAX_ITERATIONS:
            tool_runner._add_warning(f"Iteration limit ({MAX_ITERATIONS}) reached without model conclusion.")
        elif tool_runner.call_count >= MAX_TOOL_CALLS:
            tool_runner._add_warning(f"Tool budget limit ({MAX_TOOL_CALLS}) reached without model conclusion.")

    # 3. Completeness and Evidence Check across Retrieved Context
    impact_data = None
    if request.commitment_id and request.commitment_id in tool_runner.accumulated_evidence["impacts"]:
        impact_data = tool_runner.accumulated_evidence["impacts"][request.commitment_id]
    elif request.commitment_id:
        try:
            impact_data = tool_runner.get_evidence(request.commitment_id)
        except Exception:
            pass
    elif tool_runner.accumulated_evidence["impacts"]:
        # Pick first retrieved impact
        impact_data = next(iter(tool_runner.accumulated_evidence["impacts"].values()))

    # Check for completeness warnings on selected impact
    if impact_data:
        impact_status = impact_data.get("status")
        if impact_status == "needs_verification":
            status = "partial"
            for r in impact_data.get("reasons", []):
                tool_runner._add_warning(f"Completeness limitation: {r}")

        # Check for missing owner or warning reasons
        if not impact_data.get("engineering_owner") and impact_status == "date_conflict":
            tool_runner._add_warning("Missing or ambiguous engineering owner for date conflict.")
            status = "partial"

    # Broad path completeness check
    all_impacts = list(tool_runner.accumulated_evidence["impacts"].values()) if not impact_data else None

    # Check histories for lineage
    history_data = None
    if tool_runner.accumulated_evidence["histories"]:
        history_data = next(iter(tool_runner.accumulated_evidence["histories"].values()))

    experts_data = list(tool_runner.accumulated_evidence["experts"].values())

    # Build grounded answer if model text was empty or provider failed
    is_lineage = bool(history_data is not None and not impact_data)
    if (not answer_text or answer_text.strip() == "") and experts_data:
        answer_text = _experts_answer(experts_data, _display_names(tool_runner.accumulated_evidence))
    if not answer_text or answer_text.strip() == "":
        q_type = "lineage" if is_lineage else "impact"
        answer_text = build_grounded_answer(
            question_type=q_type,
            impact_data=impact_data,
            history_data=history_data,
            all_impacts=all_impacts,
            source_records=tool_runner.accumulated_evidence.get("sources"),
        )

    # 4. Verified Citations (Scoped to active question context)
    citations: list[SourceRef] = []
    if impact_data:
        relevant_citations = impact_data.get("citations", [])
    elif history_data and not impact_data:
        relevant_citations = []
        for fc in history_data.get("forecasts", []):
            relevant_citations.extend(fc.get("citations", []))
    else:
        relevant_citations = tool_runner.accumulated_evidence.get("citations", [])
    for experts in experts_data:  # who-knows-what answers cite the chats and tickets behind them
        for expert in experts.get("experts", []):
            relevant_citations = relevant_citations + [
                {"source_id": r["source_id"], "quote": r["quote"]} for r in expert.get("reasons", [])]

    for cit in relevant_citations:
        sid = cit.get("source_id", "")
        quote = cit.get("quote", "")
        if verify_citation_exact_quote(sid, quote, repo, tool_runner.accumulated_evidence.get("sources")):
            ref = SourceRef(source_id=sid, quote=quote)
            if ref not in citations:
                citations.append(ref)

    # 5. Verified Drafts
    drafts: list[Draft] = []
    # If drafts were generated by the model calling draft_followup, validate them
    names = _display_names(tool_runner.accumulated_evidence)
    for draft_obj in tool_runner.accumulated_evidence.get("drafts", []):
        # Humanize first so the validated text is exactly the text returned.
        draft_obj = draft_obj.model_copy(update={"body": humanize_ids(draft_obj.body, names)})
        target_impact = tool_runner.accumulated_evidence["impacts"].get(draft_obj.commitment_id)
        if target_impact:
            val_d, d_warn = validate_draft(draft_obj, target_impact, repo, tool_runner.accumulated_evidence.get("sources"))
            for w in d_warn:
                tool_runner._add_warning(w)
            if val_d:
                drafts.append(val_d)
        else:
            tool_runner._add_warning(
                f"Draft rejected: commitment '{draft_obj.commitment_id}' was never retrieved in evidence."
            )

    # If no drafts were called by model but a date_conflict exists with valid owners, generate grounded drafts
    if not drafts and impact_data and impact_data.get("status") == "date_conflict":
        cid = impact_data["commitment_id"]
        eng_owner = impact_data.get("engineering_owner")
        acc_owner = impact_data.get("account_owner")
        blockers = impact_data.get("blockers", [])
        dec_ids = [b["decision_id"] for b in blockers if b.get("decision_id")]

        cust_name = impact_data.get("customer", {}).get("name") or "Customer"
        comm_title = impact_data.get("title") or cid
        due_date_str = _human_date(impact_data.get("due_at")) if impact_data.get("due_at") else "the target date"

        blocker_names = [b.get("name") or b.get("work_item_name") or b.get("work_item_id") for b in blockers]
        blockers_str = ", ".join(filter(None, blocker_names)) or "upstream component"
        dec_ids_str = ", ".join(dec_ids) if dec_ids else "active decision"

        # Filter citations for this commitment (promise + dependency + revised forecast)
        supported_cits = [
            SourceRef(source_id=c["source_id"], quote=c["quote"])
            for c in impact_data.get("citations", [])
            if verify_citation_exact_quote(c["source_id"], c["quote"], repo, tool_runner.accumulated_evidence.get("sources"))
        ]

        # Internal escalation draft constructed directly (does not call tool_runner.draft_followup)
        if eng_owner and eng_owner.get("id"):
            eng_name = eng_owner.get("name", "there")
            acc_name = acc_owner.get("name", "the account lead") if acc_owner else "the account lead"
            latest = max((b.get("available_at") for b in blockers if b.get("available_at")), default=None)
            slip = f" is now forecast for {_human_date(latest)}" if latest else " has slipped"
            esc_body = (
                f"Hi {eng_name}, {blockers_str}{slip} ({dec_ids_str}). "
                f"That lands after {cust_name}'s {comm_title} promise, due {due_date_str}. "
                f"Could you set up a replanning sync with {acc_name} to agree options before we update the customer?"
            )
            raw_esc = Draft(
                kind="internal_escalation",
                commitment_id=cid,
                assignee_id=eng_owner["id"],
                body=esc_body,
                citations=supported_cits,
                based_on_decision_ids=dec_ids,
            )
            val_esc, esc_warn = validate_draft(raw_esc, impact_data, repo, tool_runner.accumulated_evidence.get("sources"))
            for w in esc_warn:
                tool_runner._add_warning(w)
            if val_esc:
                drafts.append(val_esc)
        else:
            tool_runner._add_warning(f"Skipping internal escalation draft for {cid}: missing engineering owner.")

        # Customer update draft constructed directly
        if acc_owner and acc_owner.get("id"):
            cust_body = (
                f"Hi {cust_name} team, a change in an upstream dependency ({blockers_str}) affects the "
                f"schedule for {comm_title}. Our engineering leads are reviewing the delivery plan now, "
                f"and we will follow up with an update as soon as it is agreed."
            )
            raw_cust = Draft(
                kind="customer_update",
                commitment_id=cid,
                assignee_id=acc_owner["id"],
                body=cust_body,
                citations=supported_cits[:1],
                based_on_decision_ids=dec_ids,
            )
            val_cust, cust_warn = validate_draft(raw_cust, impact_data, repo, tool_runner.accumulated_evidence.get("sources"))
            for w in cust_warn:
                tool_runner._add_warning(w)
            if val_cust:
                drafts.append(val_cust)
        else:
            tool_runner._add_warning(f"Skipping customer update draft for {cid}: missing account owner.")

    # 6. Version drift check
    final_version = repo.get_version()
    if tool_runner.latest_evidence_version and tool_runner.latest_evidence_version != current_version:
        tool_runner._add_warning(
            f"Evidence version changed during execution: started with {current_version}, "
            f"saw {tool_runner.latest_evidence_version} in evidence."
        )
        status = "partial"
        current_version = tool_runner.latest_evidence_version
    elif final_version != current_version:
        tool_runner._add_warning(
            f"Evidence version changed during execution: started with {current_version}, now {final_version}."
        )
        status = "partial"
        current_version = final_version

    answer_text = humanize_ids(answer_text, _display_names(tool_runner.accumulated_evidence))

    return AgentResponse(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        evidence_version=current_version,
        status=status,  # type: ignore[arg-type]
        answer=answer_text,
        citations=citations,
        drafts=drafts,
        tool_trace=tool_runner.trace,
        warnings=tool_runner.warnings,
    )


async def run_agent(
    request: AgentRunRequest,
    tools: AgentTools | GraphRepositoryProtocol,
    provider: LLMProvider | None = None,
    now_ms: int | None = None,
) -> AgentResponse:
    """Execute bounded AI reasoning across impact/owners or decision lineage.

    Enforces total timeout deadline of 30 seconds.
    """
    if not isinstance(tools, AgentTools):
        tool_runner = AgentTools(repo=tools, as_of=now_ms)
    else:
        tool_runner = tools

    try:
        return await asyncio.wait_for(
            _execute_agent_run(request, tool_runner, provider, now_ms),
            timeout=TOTAL_AGENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        tool_runner._add_warning(f"Agent exceeded total deadline of {TOTAL_AGENT_TIMEOUT_SECONDS}s.")
        current_version = tool_runner.repo.get_version()
        return AgentResponse(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            evidence_version=current_version,
            status="partial",
            answer="The agent exceeded the agreed execution deadline. Partial evidence retrieved.",
            citations=[],
            drafts=[],
            tool_trace=tool_runner.trace,
            warnings=tool_runner.warnings,
        )
