import { getActions } from '../api/actions';
import { useEffect, useRef } from 'react';
import { errorMessage } from '../api/client';
import type { Impact } from '../api/types';
import { useResource } from '../hooks/useResource';
import { dateTime } from '../lib/dates';
import { InlineNotice } from './InlineNotice';
import { SourceButton, type OpenSource } from './SourceButton';

export function SavedActions({
  commitmentId,
  version,
  revision,
  impact,
  onSource,
  onStale,
}: {
  commitmentId: string;
  version: string;
  revision: number;
  impact?: Impact;
  onSource: OpenSource;
  onStale: (observedVersion: string) => void;
}) {
  const result = useResource(`actions:${commitmentId}:${version}:${revision}`, signal => getActions(commitmentId, signal));
  const staleHandler = useRef(onStale); staleHandler.current = onStale;
  // The parent owns the refresh guard; this panel unmounts on workspace reload.
  useEffect(() => {
    if (result.data && result.data.evidence_version !== version) {
      staleHandler.current(result.data.evidence_version);
    }
  }, [result.data, version]);

  return <section className="saved-actions" aria-label="Saved reviewed actions"><div className="section-heading"><h3>Saved actions</h3>{result.data && <span className="small muted">{result.data.actions.length}</span>}</div>
    {result.loading && <p className="small muted" role="status">Loading saved actions…</p>}
    {!!result.error && <InlineNotice tone="error">{errorMessage(result.error)}</InlineNotice>}
    {result.data && result.data.evidence_version !== version && <InlineNotice>The saved-action context changed. Refresh the workspace before reviewing.</InlineNotice>}
    {result.data?.actions.length === 0 && <p className="small muted">Reviewed follow-ups will appear here after saving.</p>}
    {result.data?.actions.map(action => {
      const assigneeName = impact
        ? action.assignee_id === impact.engineering_owner?.id
          ? `${impact.engineering_owner.name} (${action.assignee_id})`
          : action.assignee_id === impact.account_owner?.id
            ? `${impact.account_owner.name} (${action.assignee_id})`
            : action.assignee_id
        : action.assignee_id;
      return <details className="saved-action" key={action.id}><summary>{action.kind === 'internal_escalation' ? 'Internal escalation' : 'Customer update'}<span className="small muted">{action.evidence_version === version ? 'Reviewed' : 'Needs re-review'}</span></summary>
        <p className="small muted">{dateTime(action.created_at)} · Assignee {assigneeName}</p><p className="preserve-text">{action.body}</p><div className="citation-row">{action.citations.map((citation, i) => <SourceButton key={i} source={citation} onOpen={onSource} label={`Evidence ${i + 1}`} />)}</div>
      </details>;
    })}
  </section>;
}
