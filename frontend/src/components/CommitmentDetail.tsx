import { CornerDownRight } from 'lucide-react';
import { useEffect } from 'react';
import { getHistory } from '../api/impacts';
import { ApiError, errorMessage } from '../api/client';
import type { HistoryResponse, Impact, Person } from '../api/types';
import { useResource } from '../hooks/useResource';
import { fullDate } from '../lib/dates';
import { forecastAt, requiredRoots } from '../lib/evidence';
import { EvidencePath } from './EvidencePath';
import { ForecastHistory } from './ForecastHistory';
import { InlineNotice } from './InlineNotice';
import { SourceButton, type OpenSource } from './SourceButton';
import { StatusBadge } from './StatusBadge';

function Owner({ person, role }: { person: Person | null; role: string }) {
  return <div className="owner"><span className="avatar" aria-hidden="true">{person ? person.name.slice(0, 2).toUpperCase() : '?'}</span><div><div>{person?.name ?? 'Owner needs verification'}</div><div className="small muted">{role}</div></div></div>;
}
export function CommitmentDetail({ impact, version, asOf, onSource, onRefresh, onEvidenceReady }: { impact: Impact; version: string; asOf: number; onSource: OpenSource; onRefresh: () => void; onEvidenceReady: (context: string | null) => void }) {
  const roots = requiredRoots(impact);
  const nodes = [...new Map(impact.paths.flatMap(path => path.nodes).filter(node => !['customer', 'commitment'].includes(node.kind)).map(node => [node.id, node])).values()];
  const ids = [...new Set([...nodes.map(node => node.id), ...impact.blockers.map(blocker => blocker.work_item_id)])];
  const history = useResource(`history:${version}:${impact.commitment_id}:${ids.join(',')}`, async signal => {
    const results = await Promise.all(ids.map(async id => [id, await getHistory(id, signal)] as const));
    if (results.some(([, result]) => result.evidence_version !== version)) throw new ApiError(409, 'stale_evidence', 'The forecast history changed. Refresh the workspace before reviewing.');
    return Object.fromEntries(results) as Record<string, HistoryResponse>;
  });
  const labels = Object.fromEntries(nodes.map(node => [node.id, node.label]));
  const evidenceReady = !!history.data && roots.length > 0 && ids.every(id => forecastAt(history.data![id]?.forecasts ?? [], asOf));
  useEffect(() => { onEvidenceReady(evidenceReady ? `${version}:${impact.commitment_id}` : null); return () => onEvidenceReady(null); }, [evidenceReady, version, impact.commitment_id, onEvidenceReady]);
  const terminalIds = [...new Set(impact.paths.flatMap(path => path.nodes.filter(node => !['customer', 'commitment'].includes(node.kind) && !path.edges.some(edge => edge.from_id === node.id)).map(node => node.id)))];
  return <main className="commitment-detail" aria-label="Selected commitment" aria-busy={history.loading}>
    <div className="detail-top"><span className="small muted">{impact.customer.name} / Customer commitment</span><StatusBadge status={impact.status} /></div>
    <h2>{impact.title}</h2><p className="detail-subtitle">A customer promise connected to engineering delivery.</p>
    <div className="date-comparison"><div><span className="date-label">Promised by</span><strong>{fullDate(impact.due_at)}</strong></div>
      {roots.map(id => { const forecast = history.data && forecastAt(history.data[id]?.forecasts ?? [], asOf); return <div key={id}><span className="date-label">Recorded feature forecast{roots.length > 1 ? ` · ${labels[id] || id}` : ''}</span><strong>{forecast ? fullDate(forecast.available_at) : history.loading ? 'Loading…' : 'Needs verification'}</strong></div>; })}
      {impact.blockers.length ? impact.blockers.map(blocker => <div className="date-conflict" key={blocker.forecast_id}><span className="date-label">Blocking dependency · {blocker.name}</span><strong>{fullDate(blocker.available_at)}</strong></div>) : terminalIds.filter(id => !roots.includes(id)).map(id => { const forecast = history.data && forecastAt(history.data[id]?.forecasts ?? [], asOf); return <div key={id}><span className="date-label">Recorded dependency · {labels[id] || id}</span><strong>{forecast ? fullDate(forecast.available_at) : history.loading ? 'Loading…' : 'Needs verification'}</strong></div>; })}
    </div>
    {!roots.length && <InlineNotice>No required feature was identified in the returned evidence. Verify the path before reviewing.</InlineNotice>}
    {!!history.error && <InlineNotice tone="error">{errorMessage(history.error)} <button className="text-button" onClick={onRefresh}>Refresh workspace</button></InlineNotice>}
    {impact.reasons.map((reason, i) => <p className="impact-reason" key={i}><CornerDownRight size={15} aria-hidden="true" />{reason}</p>)}
    {impact.status === 'date_conflict' && <p className="small muted replan-note">Replanning needed. The feature date is a recorded forecast, not a recalculated schedule.</p>}
    <div className="owners"><Owner person={impact.engineering_owner} role={impact.status === 'date_conflict' ? 'Blocking work owner' : 'Required work owner'} /><Owner person={impact.account_owner} role="Account owner" /></div>
    {(!impact.engineering_owner || !impact.account_owner) && <InlineNotice>Ownership needs verification. No assignee will be guessed.</InlineNotice>}
    <EvidencePath key={impact.commitment_id} paths={impact.paths} onSource={onSource} />
    <div className="citation-row">{impact.citations.map((citation, i) => <SourceButton key={`${citation.source_id}:${i}`} source={citation} onOpen={onSource} label={`Supporting passage ${i + 1}`} />)}</div>
    {history.data && <ForecastHistory histories={history.data} labels={labels} onSource={onSource} />}
  </main>;
}
