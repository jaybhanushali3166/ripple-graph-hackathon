import { FileText } from 'lucide-react';
import type { SourceRef } from '../api/types';
import { useSourceTitle } from '../hooks/useSourceTitles';
export type SourceSelection = { source_id: string; quote?: string; quotes?: string[] };
export type OpenSource = (source: SourceSelection) => void;
export function SourceButton({ source, onOpen, label }: { source: SourceSelection | SourceRef; onOpen: OpenSource; label?: string }) {
  const title = useSourceTitle(source.source_id);
  return <button type="button" className="source-link" onClick={() => onOpen(source)} title={title}><FileText size={12} aria-hidden="true" />{label ?? title ?? 'View source'}</button>;
}

/** One chip per source document; opening it highlights every cited passage from that document. */
export function SourceChips({ citations, onOpen }: { citations: SourceRef[]; onOpen: OpenSource }) {
  const grouped = new Map<string, string[]>();
  for (const citation of citations) {
    const quotes = grouped.get(citation.source_id) ?? [];
    if (citation.quote && !quotes.includes(citation.quote)) quotes.push(citation.quote);
    grouped.set(citation.source_id, quotes);
  }
  return <div className="citation-row">{[...grouped].map(([id, quotes]) => <SourceChip key={id} id={id} quotes={quotes} onOpen={onOpen} />)}</div>;
}

function SourceChip({ id, quotes, onOpen }: { id: string; quotes: string[]; onOpen: OpenSource }) {
  const title = useSourceTitle(id);
  return <button type="button" className="source-chip" onClick={() => onOpen({ source_id: id, quote: quotes[0], quotes })}>
    <FileText size={12} aria-hidden="true" /><span>{title ?? id}</span>{quotes.length > 1 && <span className="chip-count">{quotes.length}</span>}
  </button>;
}
