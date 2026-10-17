import { ArrowUpRight } from 'lucide-react';
import type { Impact } from '../api/types';
import { shortDate } from '../lib/dates';
import { daysLate, lateLabel } from '../lib/reasons';
import { StatusBadge } from './StatusBadge';
export function CommitmentList({
  impacts,
  selectedId,
  onSelect,
  changedIds,
  disabled = false,
}: {
  impacts: Impact[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  changedIds?: Set<string>;
  disabled?: boolean;
}) {
  return <nav className="commitment-list" aria-label="Customer commitments">
    <div className="list-heading"><span>All commitments</span><span>{String(impacts.length).padStart(2, '0')}</span></div>
    {impacts.map(impact => {
      const isChanged = changedIds?.has(impact.commitment_id);
      const late = daysLate(impact);
      return <button
        className={`commitment-row${isChanged ? ' row-status-changed' : ''}`}
        type="button"
        key={impact.commitment_id}
        disabled={disabled}
        aria-pressed={selectedId === impact.commitment_id}
        onClick={() => onSelect(impact.commitment_id)}
      >
        <span className="company-row">
          <span className="company-name"><span className="company-mark" aria-hidden="true">{impact.customer.name.slice(0, 1)}</span>{impact.customer.name}</span>
          <span className="row-right">
            {isChanged && <span className="status-changed-pill">Newly flagged</span>}
            {selectedId === impact.commitment_id && <ArrowUpRight size={14} aria-hidden="true" />}
          </span>
        </span>
        <span className="commitment-title">{impact.title}</span>
        <span className="commitment-meta"><StatusBadge status={impact.status} compact /><span className="date-nowrap">{shortDate(impact.due_at)}</span></span>
        {late !== null && <span className="late-badge late-badge-row">{lateLabel(late)}</span>}
      </button>;
    })}
    <p className="list-footnote">Every flag follows a recorded dependency.<br /><br />Dates shown in IST.</p>
  </nav>;
}
