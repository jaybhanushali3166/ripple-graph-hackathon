import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { confirmDecision, previewDecision } from '../api/decisions';
import { DecisionReviewDialog } from '../components/DecisionReviewDialog';
import type { DecisionPreview } from '../api/types';

vi.mock('../api/decisions', () => ({ previewDecision: vi.fn(), confirmDecision: vi.fn() }));
const preview = (): DecisionPreview => ({ preview_id: 'stored-preview', evidence_version: 'dataset:one', expires_at: Date.now() + 60_000, proposal: { work_item_id: 'wi_permissions', available_at: Date.parse('2026-10-28T18:29:59.999Z'), effective_at: Date.now() - 5000, supersedes_id: 'DEC-12', owner_id: 'person_priya', evidence_quote: 'Approved delivery update.' }, warnings: [] });
beforeEach(() => vi.resetAllMocks());
async function openReview() {
  const onConfirmed = vi.fn(), onStale = vi.fn();
  const onLock = vi.fn();
  const view = render(<DecisionReviewDialog version="dataset:one" disabled={false} onLock={onLock} onConfirmed={onConfirmed} onStale={onStale} />);
  await userEvent.click(screen.getByRole('button', { name: 'Review decision' }));
  fireEvent.change(screen.getByLabelText('Approved engineering note'), { target: { value: 'Approved delivery update.' } });
  await userEvent.click(screen.getByRole('button', { name: 'Preview decision' }));
  return { onConfirmed, onStale, onLock, view };
}
describe('immutable decision review', () => {
  it('invalidates the preview when the reviewed source text changes', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    await openReview();
    expect(await screen.findByRole('button', { name: 'Confirm reviewed update' })).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Approved engineering note'), { target: { value: 'Edited note' } });
    expect(screen.queryByRole('button', { name: 'Confirm reviewed update' })).not.toBeInTheDocument();
    expect(confirmDecision).not.toHaveBeenCalled();
  });
  it('requires a fresh preview after a stale confirmation and preserves the note', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    vi.mocked(confirmDecision).mockRejectedValue(new ApiError(409, 'stale_evidence', 'Evidence changed'));
    const callbacks = await openReview();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm reviewed update' }));
    await waitFor(() => expect(callbacks.onStale).toHaveBeenCalledOnce());
    expect(screen.queryByRole('button', { name: 'Confirm reviewed update' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Approved engineering note')).toHaveValue('Approved delivery update.');
    expect(callbacks.onConfirmed).not.toHaveBeenCalled();
  });
  it('disables initial confirmation for an expired preview', async () => {
    vi.mocked(previewDecision).mockResolvedValue({ ...preview(), expires_at: Date.now() - 1000 });
    await openReview();
    expect(await screen.findByRole('button', { name: 'Confirm reviewed update' })).toBeDisabled();
    expect(screen.getByText('This preview expired. Create a fresh preview.')).toBeVisible();
  });
  it('retains a note rejected for custom effective time instead of silently changing it', async () => {
    vi.mocked(previewDecision).mockRejectedValue(new ApiError(422, 'review_required', 'Custom effective time requires review'));
    await openReview();
    expect(await screen.findByRole('alert')).toHaveTextContent('Custom effective time requires review');
    expect(screen.getByLabelText('Approved engineering note')).toHaveValue('Approved delivery update.');
  });
  it('renders "None recorded" when supersedes_id is null', async () => {
    vi.mocked(previewDecision).mockResolvedValue({
      ...preview(),
      proposal: { ...preview().proposal, supersedes_id: null },
    });
    await openReview();
    expect(await screen.findByText('None recorded')).toBeVisible();
  });
  it('reports idempotency_conflict without dropping the preview', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    vi.mocked(confirmDecision).mockRejectedValue(new ApiError(409, 'idempotency_conflict', 'Key already used'));
    const callbacks = await openReview();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm reviewed update' }));
    expect(await screen.findByText('Key already used')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Confirm reviewed update' })).toBeVisible();
    expect(callbacks.onStale).not.toHaveBeenCalled();
  });
  it('requires an explicit duplicate-risk acknowledgement before abandoning an unknown update', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    vi.mocked(confirmDecision).mockRejectedValue(new ApiError(0, 'network_error', 'Connection lost'));
    await openReview();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm reviewed update' }));
    expect(await screen.findByText(/The confirmation outcome is unknown/i)).toBeVisible();
    const confirmAbandon = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const abandonBtn = screen.getByRole('button', { name: 'Abandon update (may duplicate)' });
    expect(abandonBtn).toBeVisible();
    await userEvent.click(abandonBtn);
    expect(screen.getByText(/The confirmation outcome is unknown/i)).toBeVisible();
    expect(confirmAbandon).toHaveBeenCalledWith(expect.stringMatching(/duplicate/i));
    await userEvent.click(abandonBtn);
    expect(screen.queryByText(/The confirmation outcome is unknown/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toBeEnabled();
  });
  it('preserves the attempt across close and a changed version, then asks the mutation endpoint definitively', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    vi.mocked(confirmDecision)
      .mockRejectedValueOnce(new ApiError(0, 'network_error', 'Connection lost'))
      .mockRejectedValueOnce(new ApiError(409, 'stale_evidence', 'Another update changed the evidence.'));
    const callbacks = await openReview();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm reviewed update' }));
    await screen.findByText(/The confirmation outcome is unknown/i);
    const originalPayload = vi.mocked(confirmDecision).mock.calls[0][0];
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(callbacks.onLock).toHaveBeenLastCalledWith(false));
    callbacks.view.rerender(<DecisionReviewDialog version="dataset:two" disabled={true} externalPending={true} onLock={callbacks.onLock} onConfirmed={callbacks.onConfirmed} onStale={callbacks.onStale} />);
    expect(screen.getByRole('button', { name: 'Resolve pending update' })).toBeDisabled();
    callbacks.view.rerender(<DecisionReviewDialog version="dataset:two" disabled={false} externalPending={false} onLock={callbacks.onLock} onConfirmed={callbacks.onConfirmed} onStale={callbacks.onStale} />);
    await userEvent.click(screen.getByRole('button', { name: 'Resolve pending update' }));
    await userEvent.click(screen.getByRole('button', { name: 'Check current state' }));
    await waitFor(() => expect(callbacks.onStale).toHaveBeenCalledOnce());
    expect(confirmDecision).toHaveBeenNthCalledWith(2, originalPayload);
    expect(callbacks.onConfirmed).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Approved engineering note')).toHaveValue('Approved delivery update.');
  });
  it('marks confirmation successful only after replaying the stored request returns success', async () => {
    vi.mocked(previewDecision).mockResolvedValue(preview());
    vi.mocked(confirmDecision)
      .mockRejectedValueOnce(new ApiError(503, 'graph_unavailable', 'Graph unavailable'))
      .mockResolvedValueOnce({ decision_id: 'decision-recorded', evidence_version: 'dataset:two', changed_work_item_ids: ['wi_permissions'] });
    const callbacks = await openReview();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm reviewed update' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check current state' }));
    await waitFor(() => expect(callbacks.onConfirmed).toHaveBeenCalledOnce());
    expect(confirmDecision).toHaveBeenNthCalledWith(2, vi.mocked(confirmDecision).mock.calls[0][0]);
  });
});
