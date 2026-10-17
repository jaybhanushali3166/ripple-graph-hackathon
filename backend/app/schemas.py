"""Authoritative Pydantic v2 wire models for Ripple.

Strictly follows docs/implementation/SHARED_CONTRACT.md and Review Revision R1.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field


class Completeness(BaseModel):
    complete: bool
    truncated: bool
    warnings: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    source_id: str
    quote: str  # exact substring of stored Source.body


class PathNode(BaseModel):
    id: str
    label: str
    kind: Literal["customer", "commitment", "feature", "component", "project"]


class PathEdge(BaseModel):
    from_id: str
    to_id: str
    relation: str
    source_id: str


class EntityOwner(BaseModel):
    id: str
    name: str


class Blocker(BaseModel):
    work_item_id: str
    name: str
    forecast_id: str
    available_at: int
    decision_id: str  # non-nullable per Review Revision R1


class EvidencePath(BaseModel):
    nodes: list[PathNode]
    edges: list[PathEdge]


class Impact(BaseModel):
    commitment_id: str
    customer: EntityOwner
    title: str
    due_at: int
    status: Literal["date_conflict", "needs_verification", "no_detected_conflict"]
    reasons: list[str] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    paths: list[EvidencePath] = Field(default_factory=list)
    engineering_owner: EntityOwner | None = None
    account_owner: EntityOwner | None = None
    citations: list[SourceRef] = Field(default_factory=list)


class ImpactResponse(BaseModel):
    evidence_version: str
    as_of: int
    impacts: list[Impact]
    completeness: Completeness


class SourceResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str
    source_timestamp: int
    content_hash: str


class ForecastHistoryItem(BaseModel):
    id: str
    available_at: int
    valid_from: int
    valid_to: int | None = None
    decision_id: str  # non-nullable per Review Revision R1
    citations: list[SourceRef] = Field(default_factory=list)


class WorkItemHistoryResponse(BaseModel):
    evidence_version: str
    forecasts: list[ForecastHistoryItem]


class DecisionPreviewRequest(BaseModel):
    text: str
    source_title: str | None = None


class DecisionProposal(BaseModel):
    work_item_id: str
    available_at: int
    effective_at: int
    supersedes_id: str | None = None
    owner_id: str
    evidence_quote: str


class DecisionPreviewResponse(BaseModel):
    preview_id: str
    evidence_version: str
    expires_at: int
    proposal: DecisionProposal
    warnings: list[str] = Field(default_factory=list)


class DecisionConfirmRequest(BaseModel):
    preview_id: str
    expected_version: str
    idempotency_key: str


class DecisionConfirmResponse(BaseModel):
    decision_id: str
    evidence_version: str
    changed_work_item_ids: list[str]


class AgentRunRequest(BaseModel):
    message: str
    commitment_id: str | None = None
    expected_version: str


class Draft(BaseModel):
    kind: Literal["internal_escalation", "customer_update"]
    commitment_id: str
    assignee_id: str | None = None
    body: str
    citations: list[SourceRef] = Field(default_factory=list)
    based_on_decision_ids: list[str] = Field(default_factory=list)


class ToolTraceItem(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["ok", "error"]


class AgentResponse(BaseModel):
    run_id: str
    evidence_version: str
    status: Literal["complete", "partial"]
    answer: str
    citations: list[SourceRef] = Field(default_factory=list)
    drafts: list[Draft] = Field(default_factory=list)
    tool_trace: list[ToolTraceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ActionCreateRequest(BaseModel):
    idempotency_key: str
    expected_version: str
    commitment_id: str
    kind: Literal["internal_escalation", "customer_update"]
    assignee_id: str
    body: str
    citations: list[SourceRef]
    based_on_decision_ids: list[str]


class ActionResponseItem(BaseModel):
    id: str
    commitment_id: str
    kind: str
    assignee_id: str
    body: str
    citations: list[SourceRef]
    based_on_decision_ids: list[str]
    status: str
    evidence_version: str
    created_at: int


class ActionCreateResponse(BaseModel):
    action_id: str
    status: Literal["reviewed"] = "reviewed"
    evidence_version: str
    created_at: int


class ActionListResponse(BaseModel):
    evidence_version: str
    actions: list[ActionResponseItem]


class GraphState(BaseModel):
    id: str = "workspace"
    dataset_id: str
    revision: int


class RequestRecord(BaseModel):
    id: str
    dataset_id: str
    operation: str
    idempotency_key: str
    request_hash: str
    result_json: str
    committed_at: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str


class DemoResetResponse(BaseModel):
    status: str
    dataset_id: str
    evidence_version: str


__all__ = [
    "Completeness",
    "SourceRef",
    "PathNode",
    "PathEdge",
    "EntityOwner",
    "Blocker",
    "EvidencePath",
    "Impact",
    "ImpactResponse",
    "SourceResponse",
    "ForecastHistoryItem",
    "WorkItemHistoryResponse",
    "DecisionPreviewRequest",
    "DecisionProposal",
    "DecisionPreviewResponse",
    "DecisionConfirmRequest",
    "DecisionConfirmResponse",
    "AgentRunRequest",
    "Draft",
    "ToolTraceItem",
    "AgentResponse",
    "ActionCreateRequest",
    "ActionResponseItem",
    "ActionCreateResponse",
    "ActionListResponse",
    "GraphState",
    "RequestRecord",
    "ErrorDetail",
    "ErrorEnvelope",
    "HealthResponse",
    "DemoResetResponse",
]
