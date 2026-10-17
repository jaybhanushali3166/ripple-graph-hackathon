import { ArrowUpRight } from 'lucide-react';
import type { Impact } from '../api/types';
import { shortDate } from '../lib/dates';
import { StatusBadge } from './StatusBadge';
export function CommitmentList({ impacts, selectedId, onSelect, disabled = false }: { impacts: Impact[]; selectedId: string | null; onSelect: (id: string) => void; disabled?: boolean }) {
  return <nav className="commitment-list" aria-label="Customer commitments">
    <div className="list-heading"><span>All commitments</span><span>{String(impacts.length).padStart(2, '0')}</span></div>
    {impacts.map(impact => <button className="commitment-row" type="button" key={impact.commitment_id} disabled={disabled} aria-pressed={selectedId === impact.commitment_id} onClick={() => onSelect(impact.commitment_id)}>
      <span className="company-row"><span className="company-name"><span className="company-mark" aria-hidden="true">{impact.customer.name.slice(0, 1)}</span>{impact.customer.name}</span>{selectedId === impact.commitment_id && <ArrowUpRight size={14} aria-hidden="true" />}</span>
      <span className="commitment-title">{impact.title}</span>
      <span className="commitment-meta"><StatusBadge status={impact.status} compact /><span className="date-nowrap">{shortDate(impact.due_at)}</span></span>
    </button>)}
    <p className="list-footnote">Every flag follows a recorded dependency.<br /><br />Dates shown in IST.</p>
  </nav>;
}
