import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { getSource } from '../api/impacts';
import { errorMessage } from '../api/client';
import { useResource } from '../hooks/useResource';
import { dateTime } from '../lib/dates';
import { InlineNotice } from './InlineNotice';
import type { SourceSelection } from './SourceButton';

/** Body with every exact quote marked; overlapping quotes merge into one highlight. */
function highlight(body: string, quotes: string[]) {
  const spans = quotes.map(quote => [body.indexOf(quote), body.indexOf(quote) + quote.length] as const)
    .filter(([start]) => start >= 0).sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [start, end] of spans) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end); else merged.push([start, end]);
  }
  const parts = [];
  let at = 0;
  for (const [start, end] of merged) { parts.push(body.slice(at, start), <mark key={start}>{body.slice(start, end)}</mark>); at = end; }
  parts.push(body.slice(at));
  return parts;
}

export function SourceDrawer({ source, version, onClose, returnFocus }: { source: SourceSelection | null; version: string; onClose: () => void; returnFocus: HTMLElement | null }) {
  const result = useResource(source ? `source:${version}:${source.source_id}` : null, signal => getSource(source!.source_id, signal));
  const quotes = source?.quotes?.length ? source.quotes : source?.quote ? [source.quote] : [];
  const body = result.data?.body ?? '';
  const missing = quotes.filter(quote => !body.includes(quote));
  return <Dialog.Root open={!!source} onOpenChange={open => { if (!open) onClose(); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="drawer" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.focus(); }}>
    <div className="drawer-heading"><span className="eyebrow">Source record</span><Dialog.Close className="button button-quiet"><X size={15} aria-hidden="true" />Close</Dialog.Close></div>
    <Dialog.Title>{result.data?.title ?? 'Source evidence'}</Dialog.Title><Dialog.Description className="muted small">Stored source text. Supporting quotations are highlighted exactly.</Dialog.Description>
    {result.loading && <p className="loading-text" role="status">Loading source record…</p>}
    {!!result.error && <InlineNotice tone="error">{errorMessage(result.error)}</InlineNotice>}
    {result.data && <><div className="source-meta"><span>{result.data.type}</span><span>{dateTime(result.data.source_timestamp)}</span></div>
      {missing.length > 0 && <InlineNotice>{missing.length === 1 ? 'A cited quote does' : `${missing.length} cited quotes do`} not match this stored body. Verify the evidence.</InlineNotice>}
      <div className="source-body">{highlight(body, quotes)}</div>
      <p className="small muted">Source ID: {result.data.id}</p></>}
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
