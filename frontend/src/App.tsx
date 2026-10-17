import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Orbit, RefreshCw } from 'lucide-react';
import { demoEnabled, errorMessage } from './api/client';
import { getGraph, resetDemo, setDependency } from './api/graph';
import type { GraphEdge } from './api/types';
import { useResource } from './hooks/useResource';
import { SourceTitles, useSourceTitleMap } from './hooks/useSourceTitles';
import { humanReason } from './lib/reasons';
import { useWorkspace } from './hooks/useWorkspace';
import { CommitmentDetail } from './components/CommitmentDetail';
import { CommitmentList } from './components/CommitmentList';
import { DemoGuide } from './components/DemoGuide';
import { RippleGraph } from './components/RippleGraph';
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
  const [draftDirty, setDraftDirty] = useState(false);
  const [invalidatedVersion, setInvalidatedVersion] = useState<string | null>(null);
  const [queuedStaleRefresh, setQueuedStaleRefresh] = useState<string | null>(null);
  const [changedCommitmentIds, setChangedCommitmentIds] = useState<Set<string>>(new Set());
  const [demoBusy, setDemoBusy] = useState(false);
  // Survives grid unmounts, selection changes, and refreshes of the same evidence.
  const actionRefreshVersions = useRef<Set<string>>(new Set());
  const preConfirmStatuses = useRef<Map<string, string>>(new Map());
  const awaitingConfirmHighlight = useRef(false);
  const sourceTrigger = useRef<HTMLElement | null>(null);

  const locked = decisionLocked || actionLocked || demoBusy;
  const onDecisionLock = useCallback((value: boolean) => setDecisionLocked(value), []);
  const onActionLock = useCallback((value: boolean) => setActionLocked(value), []);
  const onEvidenceReady = useCallback((context: string | null) => setVerifiedContext(context), []);
  const onDraftDirty = useCallback((dirty: boolean) => setDraftDirty(dirty), []);

  function openSource(next: SourceSelection) {
    sourceTrigger.current = document.activeElement as HTMLElement | null;
    setSource(next);
  }

  const refresh = useCallback((message = '') => {
    setSource(null);
    setNotice(message);
    setInvalidatedVersion(null);
    setQueuedStaleRefresh(null);
    setChangedCommitmentIds(new Set());
    workspace.refresh();
  }, [workspace.refresh]);

  const canDiscardDraft = useCallback(() => !draftDirty || window.confirm(
    'You have unsaved draft edits. This action can discard them. Continue?',
  ), [draftDirty]);

  function requestRefresh(message = '') {
    if (locked) return;
    if (canDiscardDraft()) refresh(message);
  }

  function handleUserRefresh() {
    requestRefresh();
  }

  function handleStale(message: string) {
    setInvalidatedVersion(workspace.data?.evidence_version ?? null);
    setNotice(message);
    setQueuedStaleRefresh(message);
  }

  function handleActionsStale() {
    const currentVersion = workspace.data?.evidence_version;
    if (!currentVersion) return;
    const message = 'Saved actions and commitments report different evidence. Refresh and review before saving.';
    setInvalidatedVersion(currentVersion);
    setNotice(message);
    if (actionRefreshVersions.current.has(currentVersion)) return;
    actionRefreshVersions.current.add(currentVersion);
    setQueuedStaleRefresh(message);
  }

  // Never unmount a panel holding an unresolved mutation key. After a definitive
  // result unlocks it, refresh once, with the same unsaved-edit protection.
  useEffect(() => {
    if (!queuedStaleRefresh || locked) return;
    setQueuedStaleRefresh(null);
    if (canDiscardDraft()) refresh(queuedStaleRefresh);
  }, [queuedStaleRefresh, locked, canDiscardDraft, refresh]);

  function handleConfirmed() {
    awaitingConfirmHighlight.current = true;
    preConfirmStatuses.current = new Map(workspace.data?.impacts.map(i => [i.commitment_id, i.status]) ?? []);
    refresh('Decision confirmed. Commitments and forecasts have been refreshed.');
  }

  useEffect(() => {
    if (awaitingConfirmHighlight.current && workspace.data) {
      awaitingConfirmHighlight.current = false;
      const newlyChanged = new Set<string>();
      for (const impact of workspace.data.impacts) {
        const prevStatus = preConfirmStatuses.current.get(impact.commitment_id);
        if (prevStatus && prevStatus !== 'date_conflict' && impact.status === 'date_conflict') {
          newlyChanged.add(impact.commitment_id);
        }
      }
      if (newlyChanged.size > 0) {
        setChangedCommitmentIds(newlyChanged);
      }
    }
  }, [workspace.data]);

  useEffect(() => {
    if (changedCommitmentIds.size === 0) return;
    const timer = setTimeout(() => setChangedCommitmentIds(new Set()), 5000);
    return () => clearTimeout(timer);
  }, [changedCommitmentIds]);

  const version = workspace.data?.evidence_version ?? null;
  const atRisk = workspace.data?.impacts.filter(impact => impact.status === 'date_conflict') ?? [];
  const conflicts = atRisk.length;
  const sourceTitles = useSourceTitleMap(version);
  const graph = useResource(version ? `graph:${version}` : null, getGraph);
  const impactsById = new Map(workspace.data?.impacts.map(impact => [impact.commitment_id, impact]) ?? []);

  async function runDemoChange(change: () => Promise<unknown>, message: string, highlight = false) {
    if (locked || !canDiscardDraft()) return;
    setDemoBusy(true);
    if (highlight) {
      awaitingConfirmHighlight.current = true;
      preConfirmStatuses.current = new Map(workspace.data?.impacts.map(i => [i.commitment_id, i.status]) ?? []);
    }
    try { await change(); refresh(message); }
    catch (cause) { awaitingConfirmHighlight.current = false; setNotice(errorMessage(cause)); }
    finally { setDemoBusy(false); }
  }

  function handleReset() {
    if (!window.confirm('Reset the shared demo to its starting state? Anyone else viewing will see the reset too.')) return;
    void runDemoChange(resetDemo, 'Demo reset. Every promise is back on its original plan.');
  }

  function handleToggle(edge: GraphEdge, present: boolean, label: string) {
    if (!version) return;
    const prompt = present
      ? `Restore the recorded dependency "${label}"? Impacts are recomputed from the graph.`
      : `Cut "${label}"? Ripple recomputes every promise from the graph without it. You can restore it afterwards.`;
    if (!window.confirm(prompt)) return;
    void runDemoChange(
      () => setDependency({ from_id: edge.from_id, to_id: edge.to_id, present, expected_version: version }),
      present ? `Restored: ${label}. Impacts recomputed from the graph.` : `Cut: ${label}. Impacts recomputed from the graph without it.`,
      present,
    );
  }

  return (
    <SourceTitles.Provider value={sourceTitles}>
    <div className="app-frame">
      <a className="skip-link" href="#workspace">Skip to commitments</a>
      {demoEnabled && DemoControls && (
        <Suspense>
          <DemoControls disabled={locked} onBeforeChange={canDiscardDraft} onChange={() => refresh()} />
        </Suspense>
      )}
      <div className="app-shell">
        <header className="app-chrome">
          <a href="/" className="wordmark" aria-label="Ripple home">
            <Orbit size={23} strokeWidth={1.4} aria-hidden="true" />
            ripple
          </a>
          <div className="breadcrumbs">
            <span>/</span>
            <strong>Harbor</strong>
            <span>Commitment desk</span>
          </div>
          <span className="synthetic-label">Synthetic demo data</span>
        </header>

        <div className="workspace-heading">
          <div>
            <p className="eyebrow">The customer promise, connected.</p>
            <h1>Commitments</h1>
            <p className="muted">
              {workspace.data
                ? `${workspace.data.impacts.length} promises tracked · ${conflicts ? `${conflicts} at risk: ${atRisk.map(impact => impact.customer.name).join(', ')}` : 'All on track'}`
                : 'Trace delivery changes to the promises that depend on them.'}
            </p>
          </div>
          <div className="heading-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={locked || workspace.loading}
              onClick={handleUserRefresh}
              aria-label="Refresh workspace"
            >
              <RefreshCw size={15} aria-hidden="true" />
              <span className="refresh-label">Refresh</span>
            </button>
            <DecisionReviewDialog
              version={version}
              impacts={workspace.data?.impacts}
              disabled={!version || actionLocked || invalidatedVersion === version}
              externalPending={actionLocked}
              onBeforeOpen={canDiscardDraft}
              onLock={onDecisionLock}
              onConfirmed={handleConfirmed}
              onStale={() => handleStale('The evidence changed. Review current facts before submitting again.')}
            />
          </div>
        </div>

        {notice && (
          <div className="workspace-notice">
            <InlineNotice tone="info">{notice}</InlineNotice>
          </div>
        )}
        {workspace.data && (!workspace.data.completeness.complete || workspace.data.completeness.truncated || workspace.data.completeness.warnings.length > 0) && (
          <div className="workspace-notice">
            <InlineNotice>
              {workspace.data.completeness.truncated && <p>Results are bounded or truncated. They are not exhaustive.</p>}
              {!workspace.data.completeness.complete && <p>Some evidence needs verification.</p>}
              {workspace.data.completeness.warnings.map((warning, i) => {
                const [id, ...rest] = warning.split(': ');
                const impact = impactsById.get(id);
                return <p key={i}>{impact ? `${impact.customer.name}: ${humanReason(rest.join(': '), impact)}` : warning}</p>;
              })}
            </InlineNotice>
          </div>
        )}
        {workspace.data && !workspace.error && (
          <div className="workspace-band">
            <DemoGuide conflicts={conflicts} cutEdges={graph.data?.removed_edges.length ?? 0} busy={locked || workspace.loading} onReset={handleReset} />
            {graph.data && graph.data.evidence_version === version && (
              <RippleGraph
                graph={graph.data}
                impacts={workspace.data.impacts}
                selectedId={workspace.selected?.commitment_id ?? null}
                changedIds={changedCommitmentIds}
                busy={locked || workspace.loading}
                onSelect={id => {
                  if (!locked && (id === workspace.selected?.commitment_id || canDiscardDraft())) {
                    setSource(null);
                    workspace.select(id);
                  }
                }}
                onToggle={handleToggle}
              />
            )}
            {!!graph.error && <InlineNotice tone="error">The graph view is unavailable: {errorMessage(graph.error)}</InlineNotice>}
          </div>
        )}
        <div id="workspace" className={workspace.data?.impacts.length ? 'workspace-grid' : 'workspace-empty'} aria-busy={workspace.loading}>
          {workspace.loading && <div className="empty-state" role="status"><span className="loading-dot" />Loading commitments and evidence…</div>}
          {!!workspace.error && (
            <div className="empty-state">
              <h2>The workspace is unavailable.</h2>
              <InlineNotice tone="error">{errorMessage(workspace.error)}</InlineNotice>
              <p className="muted">Live mode needs the backend at <code>/api</code>. A failed live request is never replaced with sample data.</p>
              <button type="button" className="button" onClick={() => refresh()}>Retry connection</button>
            </div>
          )}
          {workspace.data && workspace.data.impacts.length === 0 && (
            <div className="empty-state">
              <h2>No commitments recorded yet.</h2>
              <p className="muted">Add the synthetic company dataset through the backend to begin.</p>
            </div>
          )}
          {workspace.data && workspace.selected && (
            <>
              <CommitmentList
                impacts={workspace.data.impacts}
                selectedId={workspace.selected.commitment_id}
                changedIds={changedCommitmentIds}
                disabled={locked}
                onSelect={id => {
                  if (!locked && (id === workspace.selected?.commitment_id || canDiscardDraft())) {
                    setSource(null);
                    workspace.select(id);
                  }
                }}
              />
              <CommitmentDetail
                key={`${version}:${workspace.selected.commitment_id}`}
                impact={workspace.selected}
                version={version!}
                asOf={workspace.data.as_of}
                onSource={openSource}
                onRefresh={handleUserRefresh}
                onEvidenceReady={onEvidenceReady}
              />
              <FollowUpPanel
                key={`followup:${version}:${workspace.selected.commitment_id}`}
                impact={workspace.selected}
                version={version!}
                evidenceReady={invalidatedVersion !== version && verifiedContext === `${version}:${workspace.selected.commitment_id}`}
                onSource={openSource}
                onLock={onActionLock}
                onDraftDirty={onDraftDirty}
                onStale={() => handleStale('The evidence changed. Review the latest facts before saving this draft.')}
                onActionsStale={handleActionsStale}
              />
            </>
          )}
        </div>
        <footer className="app-footer">
          <span>Source-backed decisions. Accountable follow-through.</span>
          <span>Harbor · Fictional company · All dates IST</span>
        </footer>
      </div>
      <SourceDrawer source={source} version={version ?? ''} onClose={() => setSource(null)} returnFocus={sourceTrigger.current} />
    </div>
    </SourceTitles.Provider>
  );
}
