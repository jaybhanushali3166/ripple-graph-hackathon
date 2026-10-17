import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { getSource } from '../api/impacts';
import { errorMessage } from '../api/client';
import { useResource } from '../hooks/useResource';
import { dateTime } from '../lib/dates';
import { InlineNotice } from './InlineNotice';
import type { SourceSelection } from './SourceButton';

export function SourceDrawer({ source, version, onClose, returnFocus }: { source: SourceSelection | null; version: string; onClose: () => void; returnFocus: HTMLElement | null }) {
  const result = useResource(source ? `source:${version}:${source.source_id}` : null, signal => getSource(source!.source_id, signal));
  const quote = source?.quote;
  const index = quote && result.data ? result.data.body.indexOf(quote) : -1;
  return <Dialog.Root open={!!source} onOpenChange={open => { if (!open) onClose(); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="drawer" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.focus(); }}>
    <div className="drawer-heading"><span className="eyebrow">Source record</span><Dialog.Close className="button button-quiet"><X size={15} aria-hidden="true" />Close</Dialog.Close></div>
    <Dialog.Title>{result.data?.title ?? 'Source evidence'}</Dialog.Title><Dialog.Description className="muted small">Stored source text. Supporting quotations are highlighted exactly.</Dialog.Description>
    {result.loading && <p className="loading-text" role="status">Loading source record…</p>}
    {!!result.error && <InlineNotice tone="error">{errorMessage(result.error)}</InlineNotice>}
    {result.data && <><div className="source-meta"><span>{result.data.type}</span><span>{dateTime(result.data.source_timestamp)}</span></div>
      {quote && index === -1 && <InlineNotice>The cited quote does not match this stored body. Verify the evidence.</InlineNotice>}
      <div className="source-body">{quote && index >= 0 ? <>{result.data.body.slice(0, index)}<mark>{quote}</mark>{result.data.body.slice(index + quote.length)}</> : result.data.body}</div>
      <p className="small muted">Source ID: {result.data.id}</p></>}
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
