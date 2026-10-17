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
  render(<DecisionReviewDialog version="dataset:one" disabled={false} onLock={vi.fn()} onConfirmed={onConfirmed} onStale={onStale} />);
  await userEvent.click(screen.getByRole('button', { name: 'Review decision' }));
  fireEvent.change(screen.getByLabelText('Approved engineering note'), { target: { value: 'Approved delivery update.' } });
  await userEvent.click(screen.getByRole('button', { name: 'Preview decision' }));
  return { onConfirmed, onStale };
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
});
