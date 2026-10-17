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

    # Build grounded answer if model text was empty or provider failed
    is_lineage = bool(history_data is not None and not impact_data)
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
    for draft_obj in tool_runner.accumulated_evidence.get("drafts", []):
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
        due_date_str = ist_date(impact_data.get("due_at")) if impact_data.get("due_at") else "target date"

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
            esc_body = (
                f"Hi {eng_name}, the delivery schedule revision for {blockers_str} under "
                f"{dec_ids_str} conflicts with {cust_name}'s commitment '{comm_title}' "
                f"({cid}) due on {due_date_str}. "
                f"Please coordinate an escalation sync with {acc_name} to replan delivery timelines."
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
                f"Dear {cust_name} team, our engineering review indicates a schedule "
                f"revision for upstream {blockers_str} dependencies affecting '{comm_title}'. "
                f"We are reviewing delivery targets with our engineering leads and will share an updated roadmap alignment shortly."
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
