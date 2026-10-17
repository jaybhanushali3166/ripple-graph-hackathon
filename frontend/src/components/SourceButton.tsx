import { FileText } from 'lucide-react';
import type { SourceRef } from '../api/types';
export type SourceSelection = { source_id: string; quote?: string };
export type OpenSource = (source: SourceSelection) => void;
export function SourceButton({ source, onOpen, label = 'View source' }: { source: SourceSelection | SourceRef; onOpen: OpenSource; label?: string }) {
  return <button type="button" className="source-link" onClick={() => onOpen(source)}><FileText size={12} aria-hidden="true" />{label}</button>;
}
