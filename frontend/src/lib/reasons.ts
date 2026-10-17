import type { Impact } from '../api/types';
import { fullDate } from './dates';

const DAY = 86_400_000;
const ID = /\b(?:com|wi|person|cust|src|fc|team)_[A-Za-z0-9_]+\b/g;

/** Whole days the latest blocker lands after the promise; null without a blocker. */
export function daysLate(impact: Impact): number | null {
  if (!impact.blockers.length) return null;
  const latest = Math.max(...impact.blockers.map(blocker => blocker.available_at));
  return Math.max(1, Math.round((latest - impact.due_at) / DAY));
}

export const lateLabel = (days: number) => `${days} ${days === 1 ? 'day' : 'days'} late`;

/** Display names for every ID an impact mentions. */
export function impactLabels(impact: Impact): Record<string, string> {
  const labels: Record<string, string> = { [impact.commitment_id]: `${impact.customer.name}'s ${impact.title}`, [impact.customer.id]: impact.customer.name };
  for (const node of impact.paths.flatMap(path => path.nodes)) if (!(node.id in labels)) labels[node.id] = node.label;
  for (const blocker of impact.blockers) labels[blocker.work_item_id] = blocker.name;
  for (const person of [impact.engineering_owner, impact.account_owner]) if (person) labels[person.id] = person.name;
  return labels;
}

export const replaceIds = (text: string, labels: Record<string, string>) => text.replace(ID, id => labels[id] ?? id);

/** Turns a backend reason ("<code>: <machine text>") into a sentence for people. */
export function humanReason(reason: string, impact: Impact): string {
  const labels = impactLabels(impact);
  const [code, rest = ''] = reason.includes(': ') ? [reason.slice(0, reason.indexOf(': ')), reason.slice(reason.indexOf(': ') + 2)] : ['', reason];
  const first = rest.match(ID)?.[0];
  const name = first ? labels[first] ?? first : 'A dependency';
  switch (code) {
    case 'dependency_after_due': {
      const blocker = impact.blockers.find(b => b.work_item_id === first);
      if (!blocker) break;
      const days = Math.max(1, Math.round((blocker.available_at - impact.due_at) / DAY));
      return `${blocker.name} is now forecast for ${fullDate(blocker.available_at)}, ${lateLabel(days).replace(' late', '')} after the ${fullDate(impact.due_at)} promise.`;
    }
    case 'missing_forecast': return `${name} has no accepted forecast, so the promise can't be checked.`;
    case 'conflicting_forecasts': return `${name} has more than one active forecast. Pick one before relying on this date.`;
    case 'missing_engineering_owner': return `No engineering owner is recorded for ${replaceIds(rest.replace(/^no owner recorded for /, ''), labels)}.`;
    case 'ambiguous_engineering_owner': return `The blocking work has different owners, so no single engineering owner can be named.`;
    case 'missing_account_owner': return `No account owner is recorded for ${impact.customer.name}.`;
    case 'ambiguous_account_owner': return `${impact.customer.name} has more than one account owner recorded.`;
    case 'depth_limit_exceeded': return `Dependencies continue beyond the checked depth, so this result may be incomplete.`;
    case 'missing_requirement': return `${impact.title} has no required work recorded.`;
    case 'missing_customer': return `${impact.title} is not linked to a customer.`;
    case 'missing_forecast_provenance': return `A forecast for ${labels[(rest.match(ID) ?? [])[1] ?? ''] ?? 'a dependency'} has no decision behind it.`;
  }
  return replaceIds(rest || reason, labels);
}

/** Strips a "<code>: " prefix from server warnings meant for people. */
export const plainWarning = (warning: string) => warning.replace(/^[a-z_]+: /, '');
