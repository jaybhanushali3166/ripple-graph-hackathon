import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getActions, saveAction } from '../api/actions';
import { runAgent } from '../api/agent';
import { ApiError } from '../api/client';
import type { AgentResponse, Impact } from '../api/types';
import { FollowUpPanel } from '../components/FollowUpPanel';
import { impactFixture } from '../mocks/fixtures';

vi.mock('../api/actions', () => ({ getActions: vi.fn(), saveAction: vi.fn() }));
vi.mock('../api/agent', () => ({ runAgent: vi.fn() }));
const version = 'dataset:one';
const impact = (): Impact => impactFixture(true, version).impacts[0];
const answer = (): AgentResponse => ({ run_id: 'run-1', evidence_version: version, status: 'complete', answer: 'DEC-12 was superseded by the revised permissions decision.', citations: [], drafts: [], tool_trace: [], warnings: [] });
beforeEach(() => { vi.resetAllMocks(); vi.mocked(getActions).mockResolvedValue({ evidence_version: version, actions: [] }); });
function panel(selected = impact()) { return render(<FollowUpPanel impact={selected} version={version} onSource={vi.fn()} onStale={vi.fn()} onLock={vi.fn()} />); }
describe('grounded follow-ups', () => {
  it('renders a complete lineage answer without inventing a draft or save control', async () => {
    vi.mocked(runAgent).mockResolvedValue(answer()); panel();
    await userEvent.click(screen.getByRole('button', { name: 'Why did the forecast change?' }));
    expect(await screen.findByText(answer().answer)).toBeVisible();
    expect(screen.queryByLabelText('Review and edit')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save reviewed draft' })).not.toBeInTheDocument();
  });
  it('does not enable saving a draft with an unresolved owner', async () => {
    const response = answer(); response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: null, body: 'Please review.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response); panel({ ...impact(), engineering_owner: null });
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    expect(await screen.findByRole('button', { name: 'Save reviewed draft' })).toBeDisabled();
    expect(saveAction).not.toHaveBeenCalled();
  });
  it('ignores an agent result that arrives after the selected panel unmounts', async () => {
    let resolve!: (response: AgentResponse) => void;
    vi.mocked(runAgent).mockImplementation(() => new Promise(done => { resolve = done; }));
    const view = panel(); await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' })); view.unmount();
    resolve(answer());
    expect(saveAction).not.toHaveBeenCalled();
  });
  it('keeps saving disabled until the feature and dependency evidence is coherent', async () => {
    const response = answer(); response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: 'person_priya', body: 'Please review.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response);
    render(<FollowUpPanel impact={impact()} version={version} evidenceReady={false} onSource={vi.fn()} onStale={vi.fn()} onLock={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    expect(await screen.findByRole('button', { name: 'Save reviewed draft' })).toBeDisabled();
  });
  it('preserves reviewed text when the server rejects an invalid Action', async () => {
    const response = answer(); response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: 'person_priya', body: 'Keep my reviewed wording.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response);
    vi.mocked(saveAction).mockRejectedValue(new ApiError(422, 'invalid_input', 'Please verify the cited passage.'));
    panel(); await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Save reviewed draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Please verify the cited passage.');
    expect(screen.getByLabelText('Review and edit')).toHaveValue('Keep my reviewed wording.');
  });
  it('allows saving a customer_update draft when account_owner is present even if engineering_owner is null', async () => {
    const response = answer();
    response.drafts = [{
      kind: 'customer_update',
      commitment_id: 'com_acme_sso',
      assignee_id: 'person_maya',
      body: 'Customer update ready.',
      citations: [{ source_id: 'src_dec12', quote: 'Approved' }],
      based_on_decision_ids: ['DEC-12'],
    }];
    vi.mocked(runAgent).mockResolvedValue(response);
    vi.mocked(saveAction).mockResolvedValue({ action_id: 'act-1', status: 'reviewed', evidence_version: version, created_at: Date.now() });
    panel({ ...impact(), engineering_owner: null, account_owner: { id: 'person_maya', name: 'Maya' } });
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    const saveButton = await screen.findByRole('button', { name: 'Save reviewed draft' });
    expect(saveButton).toBeEnabled();
    await userEvent.click(saveButton);
    expect(saveAction).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'customer_update',
      assignee_id: 'person_maya',
      body: 'Customer update ready.',
    }));
  });
  it('disables saving an internal_escalation draft when assignee does not match engineering owner', async () => {
    const response = answer();
    response.drafts = [{
      kind: 'internal_escalation',
      commitment_id: 'com_acme_sso',
      assignee_id: 'person_wrong',
      body: 'Mismatched assignee.',
      citations: [{ source_id: 'src_dec12', quote: 'Approved' }],
      based_on_decision_ids: ['DEC-12'],
    }];
    vi.mocked(runAgent).mockResolvedValue(response);
    panel(impact());
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    expect(await screen.findByRole('button', { name: 'Save reviewed draft' })).toBeDisabled();
    expect(screen.getByText(/draft assignee/i)).toBeVisible();
    expect(saveAction).not.toHaveBeenCalled();
  });
  it('does not infer save success from an older Action with the same body; checks replay the original attempt', async () => {
    const response = answer();
    response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: 'person_priya', body: 'Templated repeated text.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response);
    vi.mocked(getActions).mockResolvedValue({ evidence_version: version, actions: [{ ...response.drafts[0], id: 'older-action', assignee_id: 'person_priya', status: 'reviewed', evidence_version: version, created_at: Date.now() - 1000 }] });
    vi.mocked(saveAction)
      .mockRejectedValueOnce(new ApiError(0, 'network_error', 'Connection lost'))
      .mockRejectedValueOnce(new ApiError(503, 'graph_unavailable', 'Still unavailable'))
      .mockResolvedValueOnce({ action_id: 'new-action', status: 'reviewed', evidence_version: version, created_at: Date.now() });
    panel();
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Save reviewed draft' }));
    const originalPayload = vi.mocked(saveAction).mock.calls[0][0];
    await userEvent.click(await screen.findByRole('button', { name: 'Check current state' }));
    expect(await screen.findByText('Still unavailable')).toBeVisible();
    expect(saveAction).toHaveBeenNthCalledWith(2, originalPayload);
    expect(getActions).toHaveBeenCalledOnce();
    expect(screen.queryByText(/Reviewed draft saved\. Find it/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Check current state' }));
    expect(await screen.findByText(/Reviewed draft saved\. Find it/)).toBeVisible();
    expect(saveAction).toHaveBeenNthCalledWith(3, originalPayload);
  });
  it('requires acknowledging duplicate risk before discarding an unknown save', async () => {
    const response = answer();
    response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: 'person_priya', body: 'Reviewed text.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response);
    vi.mocked(saveAction).mockRejectedValue(new ApiError(0, 'network_error', 'Connection lost'));
    const confirmAbandon = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    panel();
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Save reviewed draft' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Abandon save (may duplicate)' }));
    expect(screen.getByRole('button', { name: 'Retry same save' })).toBeVisible();
    expect(confirmAbandon).toHaveBeenCalledWith(expect.stringMatching(/duplicate Action/));
    await userEvent.click(screen.getByRole('button', { name: 'Abandon save (may duplicate)' }));
    expect(screen.queryByRole('button', { name: 'Retry same save' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Review and edit')).toBeEnabled();
  });
  it('retains a stale reviewed draft for inspection while disabling another save', async () => {
    const response = answer();
    response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_acme_sso', assignee_id: 'person_priya', body: 'Reviewed text to retain.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response);
    vi.mocked(saveAction).mockRejectedValue(new ApiError(409, 'stale_evidence', 'Evidence changed'));
    panel();
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Save reviewed draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Evidence changed');
    expect(screen.getByLabelText('Review and edit')).toHaveValue('Reviewed text to retain.');
    expect(screen.getByRole('button', { name: 'Save reviewed draft' })).toBeDisabled();
  });
  it('explains when a returned draft belongs to another commitment', async () => {
    const response = answer();
    response.drafts = [{ kind: 'internal_escalation', commitment_id: 'com_birch_audit', assignee_id: 'person_priya', body: 'Different commitment.', citations: [{ source_id: 'src_dec12', quote: 'Approved' }], based_on_decision_ids: ['DEC-12'] }];
    vi.mocked(runAgent).mockResolvedValue(response); panel();
    await userEvent.click(screen.getByRole('button', { name: 'Affected promises & owners' }));
    expect(await screen.findByText(/this draft belongs to a different commitment/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save reviewed draft' })).toBeDisabled();
  });
});
