import { getExperts } from '../api/graph';
import { errorMessage } from '../api/client';
import { useResource } from '../hooks/useResource';
import { InlineNotice } from './InlineNotice';
import { SourceButton, type OpenSource } from './SourceButton';

const ROLE = { owns: 'Owner', discussed: 'Discussed it', member_of: 'Responsible team' };

/** People who know the work behind a promise, ranked by the graph, each reason source-backed. */
export function WhoKnows({ workItemId, label, version, onSource }: { workItemId: string; label: string; version: string; onSource: OpenSource }) {
  const result = useResource(`experts:${version}:${workItemId}`, signal => getExperts(workItemId, signal));
  return <section className="who-knows" aria-label={`Who knows ${label}`}>
    <div className="section-heading"><h3>Who knows the {label}?</h3><span className="small muted">From chats, tickets and the ownership register</span></div>
    {result.loading && <p className="small muted" role="status">Finding people…</p>}
    {!!result.error && <InlineNotice tone="error">{errorMessage(result.error)}</InlineNotice>}
    {result.data?.experts.length === 0 && <p className="small muted">No one is recorded as knowing about this work.</p>}
    <ul className="expert-list">{result.data?.experts.slice(0, 4).map(expert => <li key={expert.id} className="expert">
      <span className="avatar" aria-hidden="true">{expert.name.slice(0, 2).toUpperCase()}</span>
      <div className="expert-body">
        <div className="expert-name">{expert.name}</div>
        <div className="expert-reasons">{expert.reasons.map((reason, i) => <span key={i} className="expert-reason">
          <span className={`role-tag role-${reason.kind}`}>{reason.kind === 'member_of' && reason.team ? `${reason.team} team` : ROLE[reason.kind]}</span>
          <SourceButton source={reason} onOpen={onSource} />
        </span>)}</div>
      </div>
    </li>)}</ul>
  </section>;
}
