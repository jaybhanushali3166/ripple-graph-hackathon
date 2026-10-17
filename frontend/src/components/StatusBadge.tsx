import { Check, CircleHelp, TriangleAlert } from 'lucide-react';
import type { Impact } from '../api/types';
const labels = { date_conflict: 'Date conflict', needs_verification: 'Needs verification', no_detected_conflict: 'No detected date conflict' };
export function StatusBadge({ status, compact = false }: { status: Impact['status']; compact?: boolean }) {
  const Icon = status === 'date_conflict' ? TriangleAlert : status === 'needs_verification' ? CircleHelp : Check;
  return <span className={`status status-${status} ${compact ? 'status-compact' : ''}`}><Icon size={12} aria-hidden="true" />{labels[status]}</span>;
}
