// Scripted, browser-memory fixtures only. No graph, model, extraction, or durability claims.
import { ApiError, type Transport } from '../api/client';
import type { ActionRequest, ActionResponse, AgentRequest, AgentResponse, ConfirmRequest, DecisionPreview, Draft, SavedAction } from '../api/types';
import { canonicalNote, endOfIstDay, historyFixture, impactFixture, people, sources } from './fixtures';

export type DemoScenario = 'baseline' | 'changed' | 'missing_owner' | 'partial_ai';
let changed = false, scenario: DemoScenario = 'baseline', revision = 0, dataset = crypto.randomUUID(), effectiveAt = Date.now();
const previews = new Map<string, DecisionPreview>();
const replay = new Map<string, { payload: string; result: unknown }>();
let actions: SavedAction[] = [];
const version = () => `${dataset}:${revision}`;
export function setDemoScenario(next: DemoScenario) {
  scenario = next; changed = next === 'changed' || next === 'partial_ai'; revision = changed ? 1 : 0;
  dataset = crypto.randomUUID(); effectiveAt = Date.now(); actions = []; previews.clear(); replay.clear();
}
function fail(status: number, code: string, message: string): never { throw new ApiError(status, code, message); }
function checkVersion(expected: string) { if (expected !== version()) fail(409, 'stale_evidence', 'The workspace evidence changed. Refresh and review again.'); }
function attempt<T>(operation: string, body: { idempotency_key: string; expected_version: string }, create: () => T): T {
  const key = `${dataset}:${operation}:${body.idempotency_key}`, serialized = JSON.stringify(body), previous = replay.get(key);
  if (previous) {
    if (previous.payload !== serialized) fail(409, 'idempotency_conflict', 'This request key has already been used for different data.');
    return structuredClone(previous.result) as T;
  }
  checkVersion(body.expected_version);
  const result = create(); replay.set(key, { payload: serialized, result }); return result;
}

export const demoTransport: Transport = async (path, init) => {
  await new Promise<void>((resolve, reject) => {
    if (init?.signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
    const onAbort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { init?.signal?.removeEventListener('abort', onAbort); resolve(); }, 180);
    init?.signal?.addEventListener('abort', onAbort, { once: true });
  });
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (path === '/impacts') return impactFixture(changed, version(), scenario === 'missing_owner');
  if (path.startsWith('/sources/')) {
    const source = sources[decodeURIComponent(path.slice('/sources/'.length))];
    return source ? structuredClone({ ...source, source_timestamp: source.id === 'src_revised_permissions' ? effectiveAt : source.source_timestamp }) : fail(404, 'source_not_found', 'This source record is unavailable.');
  }
  const match = path.match(/^\/work-items\/([^/]+)\/history$/);
  if (match) return historyFixture(decodeURIComponent(match[1]), changed, version(), effectiveAt);
  if (path === '/decisions/preview') {
    if (body.text?.trim() !== canonicalNote) fail(422, 'review_required', 'This development demo uses a scripted canonical note. Live extraction requires the backend. Use the sample note to explore this flow.');
    const preview: DecisionPreview = { preview_id: crypto.randomUUID(), evidence_version: version(), expires_at: Date.now() + 15 * 60_000, proposal: { work_item_id: 'wi_permissions', available_at: endOfIstDay('2026-10-28'), effective_at: Date.now(), supersedes_id: 'DEC-12', owner_id: 'person_priya', evidence_quote: canonicalNote }, warnings: ['Scripted development preview. No extraction model was called.'] };
    previews.set(preview.preview_id, preview); return structuredClone(preview);
  }
  if (path === '/decisions/confirm') return attempt('confirm', body as ConfirmRequest, () => {
    const preview = previews.get(body.preview_id);
    if (!preview || preview.expires_at <= Date.now()) fail(410, 'preview_expired', 'The preview expired. Create a fresh preview.');
    if (changed) fail(422, 'review_required', 'This fixture update is already applied. Select the baseline scenario to rehearse again.');
    effectiveAt = preview.proposal.effective_at; changed = true; revision++;
    return { decision_id: 'dec_permissions_revised', evidence_version: version(), changed_work_item_ids: ['wi_permissions'] };
  });
  if (path === '/agent/run') {
    const input = body as AgentRequest; checkVersion(input.expected_version);
    const selected = impactFixture(changed, version(), scenario === 'missing_owner').impacts.find(impact => impact.commitment_id === input.commitment_id);
    if (!selected) fail(422, 'invalid_input', 'Select a commitment first.');
    const lineage = /why|lineage|forecast change/i.test(input.message);
    const citations = selected.citations;
    const conflict = selected.status === 'date_conflict';
    const decision = changed ? 'dec_permissions_revised' : 'DEC-12';
    const draft = (kind: Draft['kind']): Draft => ({ kind, commitment_id: selected.commitment_id, assignee_id: kind === 'internal_escalation' ? selected.engineering_owner?.id ?? null : selected.account_owner?.id ?? null, body: kind === 'internal_escalation' ? `Hi ${selected.engineering_owner?.name ?? 'team'},\n\n${selected.customer.name}’s ${selected.title.toLowerCase()} promise is due ${new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', dateStyle: 'long' }).format(selected.due_at)}. ${conflict ? 'The permissions forecast is now October 28, 2026, later than that promise. The recorded feature date has not been recalculated.' : 'No date conflict is detected on the recorded path.'}\n\nPlease confirm the delivery assumptions and any replanning needed before the account team gives an update.` : `Hi ${selected.account_owner?.name ?? 'team'},\n\nPlease review ${selected.customer.name}’s ${selected.title.toLowerCase()} commitment. ${conflict ? 'A required engineering dependency is forecast after the promised date. We are checking recovery options with engineering.' : 'No date conflict is detected on the recorded dependency path.'}\n\nConfirm the plan before communicating a revised delivery promise.`, citations, based_on_decision_ids: [conflict ? decision : `dec_baseline_${selected.paths[0].nodes[2].id}`] });
    const partial = scenario === 'partial_ai';
    const result: AgentResponse = { run_id: crypto.randomUUID(), evidence_version: version(), status: partial ? 'partial' : 'complete', answer: lineage ? (changed ? 'The revised permissions decision supersedes DEC-12 and establishes the October 28 forecast. The feature forecasts stay recorded at their prior dates; the discrepancy requires replanning.' : 'DEC-12 establishes the accepted October 21 permissions forecast. No revised decision is recorded in this baseline.') : `${selected.customer.name}: ${selected.reasons.join(' ')} Engineering: ${selected.engineering_owner?.name ?? 'needs verification'}. Account: ${selected.account_owner?.name ?? 'needs verification'}.`, citations: lineage ? [{ source_id: changed ? 'src_revised_permissions' : 'src_dec12', quote: changed ? canonicalNote : 'Approved in DEC-12: permissions service delivery is October 21, 2026. Owner: Priya.' }] : citations, drafts: lineage || partial ? [] : [draft('internal_escalation'), draft('customer_update')], tool_trace: [{ tool: lineage ? 'get_forecast_history' : 'get_evidence', arguments: { commitment_id: selected.commitment_id }, evidence_ids: citations.map(citation => citation.source_id), status: 'ok' }], warnings: ['Scripted development answer. No model or graph tool was called.', ...(partial ? ['Example partial output: drafting was unavailable.'] : [])] };
    return result;
  }
  if (path.startsWith('/actions?')) {
    const id = new URLSearchParams(path.split('?')[1]).get('commitment_id');
    return { evidence_version: version(), actions: structuredClone(actions.filter(action => action.commitment_id === id)) };
  }
  if (path === '/actions' && init?.method === 'POST') return attempt('action', body as ActionRequest, () => {
    const input = body as ActionRequest;
    if (!input.assignee_id || !people[input.assignee_id] || !input.body.trim() || !input.citations.length || !input.based_on_decision_ids.length) fail(422, 'invalid_input', 'An assignee, text, evidence, and decision are required.');
    if (input.citations.some(citation => !sources[citation.source_id]?.body.includes(citation.quote) || !citation.quote)) fail(422, 'invalid_input', 'A cited passage does not match its source.');
    const id = crypto.randomUUID(), created_at = Date.now();
    const { idempotency_key: _key, expected_version: _expected, ...draft } = input;
    actions.push({ ...draft, id, created_at, evidence_version: version(), status: 'reviewed' });
    const result: ActionResponse = { action_id: id, status: 'reviewed', evidence_version: version(), created_at }; return result;
  });
  fail(404, 'not_found', 'This development fixture route is unavailable.');
};
