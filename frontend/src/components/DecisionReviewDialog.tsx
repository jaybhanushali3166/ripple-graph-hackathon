import * as Dialog from '@radix-ui/react-dialog';
import { ArrowRight, Check, Plus, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, errorMessage, needsFreshReview } from '../api/client';
import { confirmDecision, previewDecision } from '../api/decisions';
import type { ConfirmRequest, ConfirmResponse, DecisionPreview } from '../api/types';
import { useReviewedMutation } from '../hooks/useReviewedMutation';
import { dateTime, fullDate } from '../lib/dates';
import { sampleNote } from '../lib/sample-note';
import { InlineNotice } from './InlineNotice';

export function DecisionReviewDialog({ version, disabled, onConfirmed, onLock, onStale }: { version: string | null; disabled: boolean; onConfirmed: () => void; onLock: (locked: boolean) => void; onStale: () => void }) {
  const [open, setOpen] = useState(false), [text, setText] = useState(''), [title, setTitle] = useState('Engineering delivery update');
  const [preview, setPreview] = useState<DecisionPreview | null>(null), [extracting, setExtracting] = useState(false), [error, setError] = useState<unknown>(null);
  const [now, setNow] = useState(Date.now());
  const mutation = useReviewedMutation<ConfirmRequest, ConfirmResponse>(confirmDecision);
  const blocked = extracting || mutation.blocked;
  useEffect(() => { onLock(blocked); return () => onLock(false); }, [blocked, onLock]);
  useEffect(() => { if (!open) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [open]);
  const stale = !!preview && preview.evidence_version !== version;
  const expired = !!preview && preview.expires_at <= now;
  function edit(value: string, field: 'text' | 'title') { if (field === 'text') setText(value); else setTitle(value); setPreview(null); setError(null); }
  async function createPreview() {
    if (!text.trim() || !title.trim() || extracting) return;
    setExtracting(true); setError(null); setPreview(null);
    try { setPreview(await previewDecision({ text, source_title: title })); setNow(Date.now()); }
    catch (cause) { setError(cause); }
    finally { setExtracting(false); }
  }
  async function confirm() {
    if (!preview || (!mutation.uncertain && (stale || expired))) return;
    setError(null);
    try {
      const result = await mutation.run({ preview_id: preview.preview_id, expected_version: preview.evidence_version, idempotency_key: crypto.randomUUID() });
      if (result) { setOpen(false); setPreview(null); setText(''); onConfirmed(); }
    } catch (cause) {
      setError(cause);
      if (needsFreshReview(cause)) { setPreview(null); if (cause instanceof ApiError && cause.code === 'stale_evidence') onStale(); }
    }
  }
  return <Dialog.Root open={open} onOpenChange={next => { if (!blocked) setOpen(next); }}>
    <Dialog.Trigger asChild><button className="button button-primary" disabled={disabled} type="button"><Plus size={15} aria-hidden="true" />Review decision</button></Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="decision-dialog" onEscapeKeyDown={event => { if (blocked) event.preventDefault(); }} onPointerDownOutside={event => { if (blocked) event.preventDefault(); }}>
      <div className="drawer-heading"><span className="eyebrow">Engineering update</span><Dialog.Close className="button button-quiet" disabled={blocked}><X size={15} aria-hidden="true" />Close</Dialog.Close></div>
      <Dialog.Title>Review a delivery change.</Dialog.Title><Dialog.Description className="muted">Inspect the proposed facts before updating the recorded evidence.</Dialog.Description>
      <label className="field-label" htmlFor="source-title">Source title<input id="source-title" value={title} onChange={event => edit(event.target.value, 'title')} disabled={blocked} maxLength={300} /></label>
      <label className="field-label" htmlFor="decision-note">Approved engineering note<textarea id="decision-note" value={text} onChange={event => edit(event.target.value, 'text')} disabled={blocked} placeholder="Paste a note with an explicit delivery date and year…" rows={5} /></label>
      <button type="button" className="text-button small" disabled={blocked} onClick={() => edit(sampleNote, 'text')}>Use the synthetic sample note</button>
      {!!error && <InlineNotice tone="error">{errorMessage(error)}</InlineNotice>}
      {stale && !mutation.uncertain && <InlineNotice>The evidence changed since this preview. Create a new preview and review it again.</InlineNotice>}
      {expired && !mutation.uncertain && <InlineNotice>This preview expired. Create a fresh preview.</InlineNotice>}
      {mutation.uncertain && <InlineNotice>The confirmation outcome is unknown. Retry the same reviewed submission before editing or starting another update.</InlineNotice>}
      {preview && <section className="decision-proposal" aria-label="Extracted decision preview">
        <h3>Proposed update</h3><dl>
          <div><dt>Work item</dt><dd>{preview.proposal.work_item_id}</dd></div><div><dt>Delivery forecast</dt><dd>{fullDate(preview.proposal.available_at)}</dd></div>
          <div><dt>Decision effective time</dt><dd>{dateTime(preview.proposal.effective_at)}</dd></div><div><dt>Owner ID</dt><dd>{preview.proposal.owner_id}</dd></div>
          <div><dt>Supersedes</dt><dd>{preview.proposal.supersedes_id}</dd></div><div><dt>Review expires</dt><dd>{dateTime(preview.expires_at)}</dd></div>
        </dl><blockquote>{preview.proposal.evidence_quote}</blockquote><p className="small muted">Effective time is set by the server at preview creation. Delivery dates mean end of day in IST.</p>
        {preview.warnings.map((warning, i) => <InlineNotice key={i}>{warning}</InlineNotice>)}
      </section>}
      <div className="dialog-actions"><button className="button" type="button" onClick={createPreview} disabled={blocked || !text.trim() || !title.trim()}>{extracting ? 'Creating preview…' : preview ? 'Create fresh preview' : 'Preview decision'}<ArrowRight size={14} aria-hidden="true" /></button>
        {preview && <button className="button button-primary" type="button" onClick={confirm} disabled={mutation.pending || (!mutation.uncertain && (stale || expired))}><Check size={14} aria-hidden="true" />{mutation.pending ? 'Confirming…' : mutation.uncertain ? 'Retry same confirmation' : 'Confirm reviewed update'}</button>}
      </div>
    </Dialog.Content></Dialog.Portal>
  </Dialog.Root>;
}
