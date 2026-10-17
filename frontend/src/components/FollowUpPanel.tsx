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

export function FollowUpPanel({ impact, version, onSource, onStale, onLock, evidenceReady = true }: { impact: Impact; version: string; onSource: OpenSource; onStale: () => void; onLock: (value: boolean) => void; evidenceReady?: boolean }) {
  const [message, setMessage] = useState(''), [response, setResponse] = useState<AgentResponse | null>(null), [running, setRunning] = useState(false), [error, setError] = useState<unknown>(null);
  const [draftIndex, setDraftIndex] = useState(0), [body, setBody] = useState(''), [actionsRevision, setActionsRevision] = useState(0), [saved, setSaved] = useState(false);
  const requestRef = useRef<AbortController | null>(null), generation = useRef(0);
  const mutation = useReviewedMutation<ActionRequest, ActionResponse>(saveAction);
  useEffect(() => () => { generation.current++; requestRef.current?.abort(); }, []);
  useEffect(() => { onLock(mutation.blocked); return () => onLock(false); }, [mutation.blocked, onLock]);
  const draft = response?.drafts[draftIndex];
  const canSave = evidenceReady && !!draft && draft.commitment_id === impact.commitment_id && response?.evidence_version === version && !!draft.assignee_id && !!body.trim() && draft.citations.length > 0 && draft.based_on_decision_ids.length > 0 && !!impact.engineering_owner && !!impact.account_owner;
  function chooseDraft(index: number) { setDraftIndex(index); setBody(response?.drafts[index]?.body ?? ''); setSaved(false); }
  async function ask(question: string) {
    if (!question.trim() || mutation.blocked) return;
    requestRef.current?.abort(); const controller = new AbortController(); requestRef.current = controller;
    const current = ++generation.current; setRunning(true); setError(null); setResponse(null); setSaved(false);
    try {
      const answer = await runAgent({ message: question, commitment_id: impact.commitment_id, expected_version: version }, controller.signal);
      if (current !== generation.current || controller.signal.aborted) return;
      if (answer.evidence_version !== version) throw new ApiError(409, 'stale_evidence', 'The evidence changed during this answer. Review the current workspace.');
      setResponse(answer); setDraftIndex(0); setBody(answer.drafts[0]?.body ?? '');
    } catch (cause) { if (current !== generation.current || controller.signal.aborted) return; setError(cause); if (cause instanceof ApiError && cause.code === 'stale_evidence') onStale(); }
    finally { if (current === generation.current && !controller.signal.aborted) setRunning(false); }
  }
  async function save() {
    if ((!canSave && !mutation.uncertain) || !draft) return;
    setError(null); setSaved(false);
    try {
      const result = await mutation.run({ ...draft, assignee_id: draft.assignee_id!, body, expected_version: version, idempotency_key: crypto.randomUUID() });
      if (result) { setActionsRevision(value => value + 1); setSaved(true); }
    } catch (cause) { setError(cause); if (cause instanceof ApiError && cause.code === 'stale_evidence') { setResponse(null); setBody(''); onStale(); } }
  }
  const assignee = draft?.assignee_id === impact.engineering_owner?.id ? impact.engineering_owner?.name : draft?.assignee_id === impact.account_owner?.id ? impact.account_owner?.name : draft?.assignee_id;
  return <aside className="followup-panel" aria-label="Follow-up review">
    <div className="section-heading"><h3>Follow-up</h3><SquarePen size={15} aria-hidden="true" /></div><p className="panel-intro">Investigate the evidence, then prepare an accountable next step.</p>
    <div className="prompt-choices"><button type="button" className="prompt-button" disabled={running || mutation.blocked} onClick={() => ask('Which promises are affected, and who owns the follow-up?')}><MessageSquareText size={14} aria-hidden="true" />Affected promises &amp; owners</button><button type="button" className="prompt-button" disabled={running || mutation.blocked} onClick={() => ask('Why did the permissions forecast change?')}><MessageSquareText size={14} aria-hidden="true" />Why did the forecast change?</button></div>
    <form className="question-form" onSubmit={event => { event.preventDefault(); void ask(message); }}><label htmlFor="followup-question" className="sr-only">Ask about impact or decision lineage</label><input id="followup-question" value={message} onChange={event => setMessage(event.target.value)} placeholder="Ask about impact or lineage…" disabled={mutation.blocked} /><button type="submit" className="button button-icon" aria-label="Ask about this commitment" disabled={running || mutation.blocked || !message.trim()}><Send size={14} aria-hidden="true" /></button></form>
    {running && <p className="loading-text" role="status">Investigating the recorded evidence…</p>}
    {!!error && <InlineNotice tone="error">{errorMessage(error)}</InlineNotice>}
    {mutation.uncertain && <InlineNotice>The save outcome is unknown. Retry the same submission; editing is paused to prevent a duplicate Action.</InlineNotice>}
    {response && <div className="agent-result"><div className="section-heading"><span className="eyebrow">{response.status === 'partial' ? 'Partial answer' : 'Evidence-backed answer'}</span></div><p className="agent-answer preserve-text">{response.answer}</p><div className="citation-row">{response.citations.map((citation, i) => <SourceButton key={i} source={citation} onOpen={onSource} label={`Source ${i + 1}`} />)}</div>
      {response.warnings.map((warning, i) => <InlineNotice key={i}>{warning}</InlineNotice>)}<ToolTrace trace={response.tool_trace} />
    </div>}
    {draft && <section className="draft-editor" aria-label="Draft editor"><label className="field-label" htmlFor="draft-kind">Follow-up type<select id="draft-kind" value={draftIndex} disabled={mutation.blocked} onChange={event => chooseDraft(Number(event.target.value))}>{response!.drafts.map((item, i) => <option value={i} key={i}>{item.kind === 'internal_escalation' ? 'Internal escalation' : 'Customer update'}</option>)}</select></label>
      <label htmlFor="draft-body" className="field-label">Review and edit<textarea id="draft-body" value={body} disabled={mutation.blocked} onChange={event => { setBody(event.target.value); setSaved(false); }} rows={8} /></label>
      <p className="assignee-line"><span className="avatar" aria-hidden="true">{assignee?.slice(0, 2).toUpperCase() ?? '?'}</span>Assigned to {assignee || 'owner needs verification'}</p>
      {!canSave && <p className="small muted">Saving requires current evidence, accountable owners, a nonempty draft, citations, and relevant decisions.</p>}
      <button type="button" className="button button-primary full-width" disabled={mutation.pending || (!mutation.uncertain && (!canSave || saved))} onClick={save}><Check size={15} aria-hidden="true" />{mutation.pending ? 'Saving reviewed draft…' : mutation.uncertain ? 'Retry same save' : saved ? 'Reviewed draft saved' : 'Save reviewed draft'}</button>
      <p className="small muted">Stores a reviewed draft. No message is sent.</p>{saved && <p className="save-confirmation" role="status">Reviewed draft saved. Find it under Saved actions below.</p>}
    </section>}
    <SavedActions commitmentId={impact.commitment_id} version={version} revision={actionsRevision} onSource={onSource} onStale={onStale} />
  </aside>;
}
