import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { getImpacts } from '../api/impacts';
import { getActions } from '../api/actions';
import { SavedActions } from '../components/SavedActions';
import { impactFixture } from '../mocks/fixtures';
import type { Impact } from '../api/types';

vi.mock('../api/impacts', () => ({ getImpacts: vi.fn(), getSource: vi.fn() }));
vi.mock('../api/actions', () => ({ getActions: vi.fn() }));
vi.mock('../components/DecisionReviewDialog', () => ({
  DecisionReviewDialog: ({ onConfirmed }: { onConfirmed: () => void }) => <button onClick={onConfirmed}>Confirm test decision</button>,
}));
vi.mock('../components/CommitmentDetail', () => ({
  CommitmentDetail: ({ impact, version, onEvidenceReady, onRefresh }: { impact: Impact; version: string; onEvidenceReady: (context: string | null) => void; onRefresh: () => void }) => {
    useEffect(() => { onEvidenceReady(`${version}:${impact.commitment_id}`); return () => onEvidenceReady(null); }, [version, impact.commitment_id, onEvidenceReady]);
    return <main><h2>{impact.title}</h2><button onClick={onRefresh}>Detail refresh</button></main>;
  },
}));
vi.mock('../components/FollowUpPanel', () => ({
  FollowUpPanel: ({ impact, version, onActionsStale, onStale, onDraftDirty, onLock, evidenceReady }: { impact: Impact; version: string; onActionsStale: (observed: string) => void; onStale: () => void; onDraftDirty: (dirty: boolean) => void; onLock: (locked: boolean) => void; evidenceReady: boolean }) => {
    const [body, setBody] = useState('Original draft');
    useEffect(() => { onDraftDirty(body !== 'Original draft'); return () => onDraftDirty(false); }, [body, onDraftDirty]);
    return <aside>
      <label>Review draft edits<textarea value={body} onChange={event => setBody(event.target.value)} /></label>
      <button disabled={!evidenceReady}>Save draft</button>
      <button onClick={onStale}>Report stale evidence</button>
      <button onClick={() => onLock(true)}>Hold unknown save</button>
      <button onClick={() => onLock(false)}>Resolve pending save</button>
      <SavedActions commitmentId={impact.commitment_id} version={version} revision={0} onSource={vi.fn()} onStale={onActionsStale ?? onStale} />
    </aside>;
  },
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getImpacts).mockResolvedValue(impactFixture(false, 'one'));
  vi.mocked(getActions).mockResolvedValue({ evidence_version: 'one', actions: [] });
});
afterEach(() => { vi.useRealTimers(); });

describe('workspace recovery across panel remounts', () => {
  it('refreshes only once for a persistent version mismatch even when the entire grid unmounts', async () => {
    vi.mocked(getActions).mockImplementation(async () => {
      await new Promise(resolve => setTimeout(resolve, 5));
      return { evidence_version: 'persistent-mismatch', actions: [] };
    });
    render(<App />);
    await waitFor(() => expect(getActions).toHaveBeenCalledTimes(2));
    await screen.findByText(/The saved-action context changed/);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
    expect(getImpacts).toHaveBeenCalledTimes(2);
    expect(getActions).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
  });

  it('protects edited text on selection, header refresh, and detail refresh', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    const editor = await screen.findByLabelText('Review draft edits');
    fireEvent.change(editor, { target: { value: 'Keep these edits' } });
    fireEvent.click(screen.getByRole('button', { name: /Birch/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh workspace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Detail refresh' }));
    expect(editor).toHaveValue('Keep these edits');
    expect(getImpacts).toHaveBeenCalledOnce();
    expect(window.confirm).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('button', { name: /Acme/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps declined stale-refresh edits visible but disables saving against stale evidence', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    const editor = await screen.findByLabelText('Review draft edits');
    fireEvent.change(editor, { target: { value: 'Keep my stale review notes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Report stale evidence' }));
    expect(editor).toHaveValue('Keep my stale review notes');
    expect(getImpacts).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    expect(screen.getByText(/Review the latest facts before saving/)).toBeVisible();
  });

  it('defers automatic stale refresh until an unresolved mutation is definitively resolved', async () => {
    render(<App />);
    await screen.findByLabelText('Review draft edits');
    fireEvent.click(screen.getByRole('button', { name: 'Hold unknown save' }));
    fireEvent.click(screen.getByRole('button', { name: 'Report stale evidence' }));
    await act(async () => {});
    expect(getImpacts).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Refresh workspace' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Resolve pending save' }));
    await waitFor(() => expect(getImpacts).toHaveBeenCalledTimes(2));
  });
});

describe('newly flagged commitment highlights', () => {
  async function mountWithUpdate(beforeConflict: boolean, afterConflict: boolean) {
    let currentVersion = 'one';
    vi.mocked(getImpacts)
      .mockResolvedValueOnce(impactFixture(beforeConflict, 'one'))
      .mockImplementation(async () => { currentVersion = 'two'; return impactFixture(afterConflict, currentVersion); });
    vi.mocked(getActions).mockImplementation(async () => ({ evidence_version: currentVersion, actions: [] }));
    await act(async () => { render(<App />); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Confirm test decision' })); });
  }

  it('clears highlights after five seconds without depending on impact data changes', async () => {
    vi.useFakeTimers();
    await mountWithUpdate(false, true);
    expect(screen.getAllByText('Newly flagged')).toHaveLength(2);
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByText('Newly flagged')).not.toBeInTheDocument();
  });

  it('clears the highlight when refreshing inside the five-second window', async () => {
    vi.useFakeTimers();
    await mountWithUpdate(false, true);
    expect(screen.getAllByText('Newly flagged')).toHaveLength(2);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh workspace' })); });
    expect(screen.queryByText('Newly flagged')).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(screen.queryByText('Newly flagged')).not.toBeInTheDocument();
  });

  it('does not label a resolved conflict as newly flagged', async () => {
    await mountWithUpdate(true, false);
    expect(screen.queryByText('Newly flagged')).not.toBeInTheDocument();
    expect(screen.getByText('4 promises tracked · No detected date conflicts')).toBeVisible();
  });
});
