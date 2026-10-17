import { lazy, Suspense, useCallback, useRef, useState } from 'react';
import { Orbit, RefreshCw } from 'lucide-react';
import { demoEnabled, errorMessage } from './api/client';
import { useWorkspace } from './hooks/useWorkspace';
import { CommitmentDetail } from './components/CommitmentDetail';
import { CommitmentList } from './components/CommitmentList';
import { DecisionReviewDialog } from './components/DecisionReviewDialog';
import { FollowUpPanel } from './components/FollowUpPanel';
import { InlineNotice } from './components/InlineNotice';
import { SourceDrawer } from './components/SourceDrawer';
import type { SourceSelection } from './components/SourceButton';

const DemoControls = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEMO === 'true' ? lazy(() => import('./components/DemoControls')) : null;

export default function App() {
  const workspace = useWorkspace();
  const [source, setSource] = useState<SourceSelection | null>(null), [notice, setNotice] = useState('');
  const [decisionLocked, setDecisionLocked] = useState(false), [actionLocked, setActionLocked] = useState(false);
  const [verifiedContext, setVerifiedContext] = useState<string | null>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const locked = decisionLocked || actionLocked;
  const onDecisionLock = useCallback((value: boolean) => setDecisionLocked(value), []);
  const onActionLock = useCallback((value: boolean) => setActionLocked(value), []);
  const onEvidenceReady = useCallback((context: string | null) => setVerifiedContext(context), []);
  function openSource(next: SourceSelection) { sourceTrigger.current = document.activeElement as HTMLElement | null; setSource(next); }
  function refresh(message = '') { setSource(null); setNotice(message); workspace.refresh(); }
  const version = workspace.data?.evidence_version ?? null;
  const conflicts = workspace.data?.impacts.filter(impact => impact.status === 'date_conflict').length ?? 0;
  return <div className="app-frame">
    <a className="skip-link" href="#workspace">Skip to commitments</a>
    {demoEnabled && DemoControls && <Suspense><DemoControls disabled={locked} onChange={() => refresh()} /></Suspense>}
    <div className="app-shell">
      <header className="app-chrome"><a href="/" className="wordmark" aria-label="Ripple home"><Orbit size={23} strokeWidth={1.4} aria-hidden="true" />ripple</a><div className="breadcrumbs"><span>/</span><strong>Harbor</strong><span>Commitment desk</span></div><span className="synthetic-label">Synthetic demo data</span></header>
      <div className="workspace-heading"><div><p className="eyebrow">The customer promise, connected.</p><h1>Commitments</h1><p className="muted">{workspace.data ? `${workspace.data.impacts.length} promises tracked · ${conflicts ? `${conflicts} date conflicts to review` : 'No detected date conflicts'}` : 'Trace delivery changes to the promises that depend on them.'}</p></div><div className="heading-actions"><button type="button" className="button button-quiet" disabled={locked || workspace.loading} onClick={() => refresh()} aria-label="Refresh workspace"><RefreshCw size={15} aria-hidden="true" /><span className="refresh-label">Refresh</span></button><DecisionReviewDialog version={version} disabled={!version || actionLocked} onLock={onDecisionLock} onConfirmed={() => refresh('Decision confirmed. Commitments and forecasts have been refreshed.')} onStale={() => refresh('The evidence changed. Review current facts before submitting again.')} /></div></div>
      {notice && <div className="workspace-notice"><InlineNotice tone="info">{notice}</InlineNotice></div>}
      {workspace.data && (!workspace.data.completeness.complete || workspace.data.completeness.truncated || workspace.data.completeness.warnings.length > 0) && <div className="workspace-notice"><InlineNotice>{workspace.data.completeness.truncated && <p>Results are bounded or truncated. They are not exhaustive.</p>}{!workspace.data.completeness.complete && <p>Some evidence needs verification.</p>}{workspace.data.completeness.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</InlineNotice></div>}
      <div id="workspace" className={workspace.data?.impacts.length ? 'workspace-grid' : 'workspace-empty'} aria-busy={workspace.loading}>
        {workspace.loading && <div className="empty-state" role="status"><span className="loading-dot" />Loading commitments and evidence…</div>}
        {!!workspace.error && <div className="empty-state"><h2>The workspace is unavailable.</h2><InlineNotice tone="error">{errorMessage(workspace.error)}</InlineNotice><p className="muted">Live mode needs the backend at <code>/api</code>. A failed live request is never replaced with sample data.</p><button type="button" className="button" onClick={() => refresh()}>Retry connection</button></div>}
        {workspace.data && workspace.data.impacts.length === 0 && <div className="empty-state"><h2>No commitments recorded yet.</h2><p className="muted">Add the synthetic company dataset through the backend to begin.</p></div>}
        {workspace.data && workspace.selected && <><CommitmentList impacts={workspace.data.impacts} selectedId={workspace.selected.commitment_id} disabled={locked} onSelect={id => { if (!locked) { setSource(null); workspace.select(id); } }} />
          <CommitmentDetail key={`${version}:${workspace.selected.commitment_id}`} impact={workspace.selected} version={version!} asOf={workspace.data.as_of} onSource={openSource} onRefresh={() => refresh()} onEvidenceReady={onEvidenceReady} />
          <FollowUpPanel key={`followup:${version}:${workspace.selected.commitment_id}`} impact={workspace.selected} version={version!} evidenceReady={verifiedContext === `${version}:${workspace.selected.commitment_id}`} onSource={openSource} onLock={onActionLock} onStale={() => refresh('The evidence changed. Earlier drafts are invalid; generate a fresh answer.')} />
        </>}
      </div>
      <footer className="app-footer"><span>Source-backed decisions. Accountable follow-through.</span><span>Harbor · Fictional company · All dates IST</span></footer>
    </div>
    <SourceDrawer source={source} version={version ?? ''} onClose={() => setSource(null)} returnFocus={sourceTrigger.current} />
  </div>;
}
