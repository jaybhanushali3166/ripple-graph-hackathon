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
});
