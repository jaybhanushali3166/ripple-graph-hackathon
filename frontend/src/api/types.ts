// Mirrors SHARED_CONTRACT.md R1. Validate against Pavan's published DTOs at handoff.
export type Completeness = { complete: boolean; truncated: boolean; warnings: string[] };
export type SourceRef = { source_id: string; quote: string };
export type Person = { id: string; name: string };
export type PathNode = { id: string; label: string; kind: 'customer' | 'commitment' | 'feature' | 'component' | 'project' };
export type PathEdge = { from_id: string; to_id: string; relation: string; source_id: string };
export type EvidencePath = { nodes: PathNode[]; edges: PathEdge[] };
export type Impact = {
  commitment_id: string; customer: { id: string; name: string }; title: string; due_at: number;
  status: 'date_conflict' | 'needs_verification' | 'no_detected_conflict'; reasons: string[];
  blockers: { work_item_id: string; name: string; forecast_id: string; available_at: number; decision_id: string }[];
  paths: EvidencePath[]; engineering_owner: Person | null; account_owner: Person | null; citations: SourceRef[];
};
export type ImpactResponse = { evidence_version: string; as_of: number; impacts: Impact[]; completeness: Completeness };
export type Source = { id: string; type: string; title: string; body: string; source_timestamp: number; content_hash: string };
export type Forecast = { id: string; available_at: number; valid_from: number; valid_to: number | null; decision_id: string; supersedes_id?: string | null; decision_summary?: string | null; citations: SourceRef[] };
export type HistoryResponse = { evidence_version: string; forecasts: Forecast[] };
export type PreviewRequest = { text: string; source_title: string };
export type DecisionPreview = {
  preview_id: string; evidence_version: string; expires_at: number;
  proposal: { work_item_id: string; available_at: number; effective_at: number; supersedes_id: string | null; owner_id: string; evidence_quote: string };
  warnings: string[];
};
export type ConfirmRequest = { preview_id: string; expected_version: string; idempotency_key: string };
export type ConfirmResponse = { decision_id: string; evidence_version: string; changed_work_item_ids: string[] };
export type DraftKind = 'internal_escalation' | 'customer_update';
export type Draft = { kind: DraftKind; commitment_id: string; assignee_id: string | null; body: string; citations: SourceRef[]; based_on_decision_ids: string[] };
export type AgentRequest = { message: string; commitment_id?: string; expected_version: string };
export type AgentResponse = {
  run_id: string; evidence_version: string; status: 'complete' | 'partial'; answer: string; citations: SourceRef[]; drafts: Draft[];
  tool_trace: { tool: string; arguments: Record<string, unknown>; evidence_ids: string[]; status: 'ok' | 'error' }[];
  warnings: string[];
};
export type ActionRequest = Omit<Draft, 'assignee_id'> & { assignee_id: string; expected_version: string; idempotency_key: string };
export type SavedAction = Omit<Draft, 'assignee_id'> & { id: string; assignee_id: string; status: string; evidence_version: string; created_at: number };
export type ActionsResponse = { evidence_version: string; actions: SavedAction[] };
export type ActionResponse = { action_id: string; status: 'reviewed'; evidence_version: string; created_at: number };
export type GraphNode = { id: string; label: string; kind: string };
export type GraphEdge = { from_id: string; to_id: string; relation: string; source_id: string | null };
export type GraphView = { evidence_version: string; nodes: GraphNode[]; edges: GraphEdge[]; removed_edges: GraphEdge[]; queries: Record<string, string> };
export type SourceSummary = { id: string; type: string; title: string; source_timestamp: number };
export type SourceList = { sources: SourceSummary[] };
export type ExpertReason = { kind: 'owns' | 'discussed' | 'member_of'; source_id: string; quote: string; team?: string | null };
export type Expert = { id: string; name: string; score: number; reasons: ExpertReason[] };
export type ExpertsResponse = { evidence_version: string; work_item_id: string; experts: Expert[] };
export type DependencyToggle = { from_id: string; to_id: string; present: boolean; expected_version: string };
export type DependencyToggleResponse = { evidence_version: string; from_id: string; to_id: string; present: boolean };
export type DemoResetResponse = { status: string; dataset_id: string; evidence_version: string };
