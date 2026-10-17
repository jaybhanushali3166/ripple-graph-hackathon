import { Check, MessageSquareText, Send, SquarePen } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { saveAction } from '../api/actions';
import { runAgent } from '../api/agent';
import { ApiError, errorMessage } from '../api/client';
import type { ActionRequest, ActionResponse, AgentResponse, Impact } from '../api/types';
import { useReviewedMutation } from '../hooks/useReviewedMutation';
import { InlineNotice } from './InlineNotice';
import { SavedActions } from './SavedActions';
import { SourceButton, type OpenSource } from './SourceButton';
import { ToolTrace } from './ToolTrace';

export function FollowUpPanel({
  impact,
  version,
  onSource,
  onStale,
  onLock,
  onDraftDirty,
  onActionsStale,
  evidenceReady = true,
}: {
  impact: Impact;
  version: string;
  onSource: OpenSource;
  onStale: () => void;
  onLock: (value: boolean) => void;
  onDraftDirty?: (dirty: boolean) => void;
  onActionsStale?: (observedVersion: string) => void;
  evidenceReady?: boolean;
}) {
  const [message, setMessage] = useState(''), [response, setResponse] = useState<AgentResponse | null>(null), [running, setRunning] = useState(false), [error, setError] = useState<unknown>(null);
  const [draftIndex, setDraftIndex] = useState(0), [body, setBody] = useState(''), [actionsRevision, setActionsRevision] = useState(0), [saved, setSaved] = useState(false);
  const [contextStale, setContextStale] = useState(false);
  const requestRef = useRef<AbortController | null>(null), generation = useRef(0);
  const mutation = useReviewedMutation<ActionRequest, ActionResponse>(saveAction);

  useEffect(() => () => { generation.current++; requestRef.current?.abort(); }, []);
  useEffect(() => { onLock(mutation.blocked); return () => onLock(false); }, [mutation.blocked, onLock]);

  const draft = response?.drafts[draftIndex];
  const draftOwnerValid = draft?.kind === 'internal_escalation'
    ? (!!impact.engineering_owner && draft.assignee_id === impact.engineering_owner.id)
    : draft?.kind === 'customer_update'
      ? (!!impact.account_owner && draft.assignee_id === impact.account_owner.id)
      : false;

  const canSave = !contextStale && evidenceReady &&
    !!draft &&
    draft.commitment_id === impact.commitment_id &&
    response?.evidence_version === version &&
    !!body.trim() &&
    draft.citations.length > 0 &&
    draft.based_on_decision_ids.length > 0 &&
    draftOwnerValid;

  const originalBody = response?.drafts[draftIndex]?.body ?? '';
  const isDirty = !!draft && body !== originalBody && !saved;
  useEffect(() => {
    onDraftDirty?.(isDirty);
    return () => onDraftDirty?.(false);
  }, [isDirty, onDraftDirty]);

  function getSaveDisabledReason(): string {
    if (contextStale) return 'Saving is disabled: evidence changed. Refresh the workspace and review a fresh answer.';
    if (!evidenceReady) return 'Saving is disabled: current forecast evidence for roots or blockers is missing or needs verification.';
    if (!draft) return 'Saving is disabled: no draft selected.';
    if (draft.commitment_id !== impact.commitment_id) return 'Saving is disabled: this draft belongs to a different commitment.';
    if (response?.evidence_version !== version) return 'Saving is disabled: evidence version has changed. Generate a fresh answer.';
    if (!body.trim()) return 'Saving is disabled: draft body cannot be empty.';
    if (draft.citations.length === 0) return 'Saving is disabled: draft requires supporting citations.';
    if (draft.based_on_decision_ids.length === 0) return 'Saving is disabled: draft requires relevant decisions.';
    if (draft.kind === 'internal_escalation') {
      if (!impact.engineering_owner) return 'Saving is disabled: internal escalation requires an accountable engineering owner.';
      if (draft.assignee_id !== impact.engineering_owner.id) return `Saving is disabled: draft assignee does not match engineering owner (${impact.engineering_owner.name}).`;
    }
    if (draft.kind === 'customer_update') {
      if (!impact.account_owner) return 'Saving is disabled: customer update requires an accountable account owner.';
      if (draft.assignee_id !== impact.account_owner.id) return `Saving is disabled: draft assignee does not match account owner (${impact.account_owner.name}).`;
    }
    return 'Saving requires current evidence, an accountable owner for this draft type, a nonempty draft, citations, and relevant decisions.';
  }

  function canDiscardEdits() { return !isDirty || window.confirm('This will discard your unsaved draft edits. Continue?'); }
  function chooseDraft(index: number) { if (!canDiscardEdits()) return; setDraftIndex(index); setBody(response?.drafts[index]?.body ?? ''); setSaved(false); }

  const blockerName = impact.blockers[0]?.name;
  const lineageSubject = blockerName ? blockerName.toLowerCase() : impact.title.toLowerCase();
  const lineagePrompt = `Why did the ${lineageSubject} forecast change?`;

  async function ask(question: string) {
    if (!question.trim() || mutation.blocked || contextStale || !canDiscardEdits()) return;
    requestRef.current?.abort(); const controller = new AbortController(); requestRef.current = controller;
    const current = ++generation.current; setRunning(true); setError(null); setResponse(null); setSaved(false);
    try {
      const answer = await runAgent({ message: question, commitment_id: impact.commitment_id, expected_version: version }, controller.signal);
      if (current !== generation.current || controller.signal.aborted) return;
      if (answer.evidence_version !== version) throw new ApiError(409, 'stale_evidence', 'The evidence changed during this answer. Review the current workspace.');
      setResponse(answer); setDraftIndex(0); setBody(answer.drafts[0]?.body ?? '');
    } catch (cause) { if (current !== generation.current || controller.signal.aborted) return; setError(cause); if (cause instanceof ApiError && cause.code === 'stale_evidence') { setContextStale(true); onStale(); } }
    finally { if (current === generation.current && !controller.signal.aborted) setRunning(false); }
  }

  async function save(replay = false) {
    if ((!canSave && !mutation.uncertain) || !draft) return;
    setError(null); setSaved(false);
    try {
      const result = replay
        ? await mutation.retry()
        : await mutation.run({ ...draft, assignee_id: draft.assignee_id!, body, expected_version: version, idempotency_key: crypto.randomUUID() });
      if (result) { setActionsRevision(value => value + 1); setSaved(true); }
    } catch (cause) { setError(cause); if (cause instanceof ApiError && cause.code === 'stale_evidence') { setContextStale(true); onStale(); } }
  }

  function abandonSave() {
    if (!window.confirm('The server may already have saved this Action. Abandoning forgets its retry key; saving again may create a duplicate Action. Abandon anyway?')) return;
    if (mutation.abandon()) setError(null);
  }

  const assignee = draft?.assignee_id === impact.engineering_owner?.id ? impact.engineering_owner?.name : draft?.assignee_id === impact.account_owner?.id ? impact.account_owner?.name : draft?.assignee_id;
  return <aside className="followup-panel" aria-label="Follow-up review">
    <div className="section-heading"><h3>Follow-up</h3><SquarePen size={15} aria-hidden="true" /></div><p className="panel-intro">Investigate the evidence, then prepare an accountable next step.</p>
    <div className="prompt-choices">
      <button type="button" className="prompt-button" disabled={running || mutation.blocked || contextStale} onClick={() => ask('Which promises are affected, and who owns the follow-up?')}>
        <MessageSquareText size={14} aria-hidden="true" />Affected promises &amp; owners
      </button>
      <button type="button" className="prompt-button" disabled={running || mutation.blocked || contextStale} onClick={() => ask(lineagePrompt)}>
        <MessageSquareText size={14} aria-hidden="true" />Why did the forecast change?
      </button>
    </div>
    <form className="question-form" onSubmit={event => { event.preventDefault(); void ask(message); }}><label htmlFor="followup-question" className="sr-only">Ask about impact or decision lineage</label><input id="followup-question" value={message} onChange={event => setMessage(event.target.value)} placeholder="Ask about impact or lineage…" disabled={mutation.blocked} /><button type="submit" className="button button-icon" aria-label="Ask about this commitment" disabled={running || mutation.blocked || contextStale || !message.trim()}><Send size={14} aria-hidden="true" /></button></form>
    {running && <p className="loading-text" role="status">Investigating the recorded evidence…</p>}
    {!!error && <InlineNotice tone="error">{errorMessage(error)}</InlineNotice>}
    {mutation.uncertain && <div className="uncertain-banner">
      <InlineNotice>The save outcome is unknown. Retry the same submission; editing is paused to prevent a duplicate Action.</InlineNotice>
      <div className="uncertain-actions-row">
        <button type="button" className="button small" disabled={mutation.pending} onClick={() => save(true)}>{mutation.pending ? 'Checking…' : 'Check current state'}</button>
        <button type="button" className="button button-quiet small" disabled={mutation.pending} onClick={abandonSave}>Abandon save (may duplicate)</button>
      </div>
      <p className="small muted">Abandoning an unknown save forgets its retry key. Saving again may create a duplicate.</p>
    </div>}
    {response && <div className="agent-result"><div className="section-heading"><span className="eyebrow">{response.status === 'partial' ? 'Partial answer' : 'Evidence-backed answer'}</span></div><p className="agent-answer preserve-text">{response.answer}</p><div className="citation-row">{response.citations.map((citation, i) => <SourceButton key={i} source={citation} onOpen={onSource} label={`Source ${i + 1}`} />)}</div>
      {response.warnings.map((warning, i) => <InlineNotice key={i}>{warning}</InlineNotice>)}<ToolTrace trace={response.tool_trace} />
    </div>}
    {draft && <section className="draft-editor" aria-label="Draft editor"><label className="field-label" htmlFor="draft-kind">Follow-up type<select id="draft-kind" value={draftIndex} disabled={mutation.blocked} onChange={event => chooseDraft(Number(event.target.value))}>{response!.drafts.map((item, i) => <option value={i} key={i}>{item.kind === 'internal_escalation' ? 'Internal escalation' : 'Customer update'}</option>)}</select></label>
      <label htmlFor="draft-body" className="field-label">Review and edit<textarea id="draft-body" value={body} disabled={mutation.blocked} onChange={event => { setBody(event.target.value); setSaved(false); }} rows={8} /></label>
      <p className="assignee-line"><span className="avatar" aria-hidden="true">{assignee?.slice(0, 2).toUpperCase() ?? '?'}</span>Assigned to {assignee || 'owner needs verification'}</p>
      {!canSave && <p className="small muted">{getSaveDisabledReason()}</p>}
      <button type="button" className="button button-primary full-width" disabled={mutation.pending || (!mutation.uncertain && (!canSave || saved))} onClick={() => save(mutation.uncertain)}><Check size={15} aria-hidden="true" />{mutation.pending ? 'Saving reviewed draft…' : mutation.uncertain ? 'Retry same save' : saved ? 'Reviewed draft saved' : 'Save reviewed draft'}</button>
      <p className="small muted">Stores a reviewed draft. No message is sent.</p>{saved && <p className="save-confirmation" role="status">Reviewed draft saved. Find it under Saved actions below.</p>}
    </section>}
    <SavedActions commitmentId={impact.commitment_id} version={version} revision={actionsRevision} impact={impact} onSource={onSource} onStale={onActionsStale ?? onStale} />
  </aside>;
}
