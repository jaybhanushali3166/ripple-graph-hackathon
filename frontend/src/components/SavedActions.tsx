import { getActions } from '../api/actions';
import { useEffect, useRef } from 'react';
import { errorMessage } from '../api/client';
import { useResource } from '../hooks/useResource';
import { dateTime } from '../lib/dates';
import { InlineNotice } from './InlineNotice';
import { SourceButton, type OpenSource } from './SourceButton';
export function SavedActions({ commitmentId, version, revision, onSource, onStale }: { commitmentId: string; version: string; revision: number; onSource: OpenSource; onStale: () => void }) {
  const result = useResource(`actions:${commitmentId}:${version}:${revision}`, signal => getActions(commitmentId, signal));
  const staleHandler = useRef(onStale); staleHandler.current = onStale;
  useEffect(() => { if (result.data && result.data.evidence_version !== version) staleHandler.current(); }, [result.data, version]);
  return <section className="saved-actions" aria-label="Saved reviewed actions"><div className="section-heading"><h3>Saved actions</h3>{result.data && <span className="small muted">{result.data.actions.length}</span>}</div>
    {result.loading && <p className="small muted" role="status">Loading saved actions…</p>}
    {!!result.error && <InlineNotice tone="error">{errorMessage(result.error)}</InlineNotice>}
    {result.data && result.data.evidence_version !== version && <InlineNotice>The saved-action context changed. Refresh the workspace before reviewing.</InlineNotice>}
    {result.data?.actions.length === 0 && <p className="small muted">Reviewed follow-ups will appear here after saving.</p>}
    {result.data?.actions.map(action => <details className="saved-action" key={action.id}><summary>{action.kind === 'internal_escalation' ? 'Internal escalation' : 'Customer update'}<span className="small muted">{action.evidence_version === version ? 'Reviewed' : 'Needs re-review'}</span></summary>
      <p className="small muted">{dateTime(action.created_at)} · Assignee {action.assignee_id}</p><p className="preserve-text">{action.body}</p><div className="citation-row">{action.citations.map((citation, i) => <SourceButton key={i} source={citation} onOpen={onSource} label={`Evidence ${i + 1}`} />)}</div>
    </details>)}
  </section>;
}
