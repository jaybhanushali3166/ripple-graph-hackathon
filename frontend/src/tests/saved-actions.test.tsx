import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getActions } from '../api/actions';
import { SavedActions } from '../components/SavedActions';
vi.mock('../api/actions', () => ({ getActions: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
describe('stored action evidence', () => {
  it('retains an Action original version and marks it for re-review after knowledge changes', async () => {
    vi.mocked(getActions).mockResolvedValue({ evidence_version: 'current', actions: [{ id: 'action-1', commitment_id: 'com_acme_sso', kind: 'internal_escalation', assignee_id: 'person_priya', body: 'Previously reviewed text.', citations: [], based_on_decision_ids: ['DEC-12'], status: 'reviewed', evidence_version: 'previous', created_at: Date.now() }] });
    render(<SavedActions commitmentId="com_acme_sso" version="current" revision={0} onSource={vi.fn()} onStale={vi.fn()} />);
    expect(await screen.findByText('Needs re-review')).toBeVisible();
  });
  it('invalidates the workspace when an Action read reveals newer evidence', async () => {
    vi.mocked(getActions).mockResolvedValue({ evidence_version: 'new-version', actions: [] });
    const onStale = vi.fn();
    render(<SavedActions commitmentId="com_acme_sso" version="old-version" revision={0} onSource={vi.fn()} onStale={onStale} />);
    await waitFor(() => expect(onStale).toHaveBeenCalledOnce());
  });
});
