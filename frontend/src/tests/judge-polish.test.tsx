import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { GraphView } from '../api/types';
import { RichText } from '../components/RichText';
import { RippleGraph } from '../components/RippleGraph';
import { SourceChips } from '../components/SourceButton';
import { SourceTitles } from '../hooks/useSourceTitles';
import { decisionLabel } from '../lib/decisions';
import { daysLate, humanReason, plainWarning } from '../lib/reasons';
import { endOfIstDay, impactFixture } from '../mocks/fixtures';

const changed = impactFixture(true, 'v').impacts;
const acme = changed.find(impact => impact.commitment_id === 'com_acme_sso')!;

describe('plain-language evidence', () => {
  it('turns a dependency_after_due reason into a sentence with the slip size', () => {
    const impact = { ...acme, due_at: endOfIstDay('2026-10-23') };
    expect(humanReason('dependency_after_due: wi_permissions is forecast available 2026-10-28, after com_acme_sso is due 2026-10-23', impact))
      .toBe('Permissions service is now forecast for 28 October 2026, 5 days after the 23 October 2026 promise.');
    expect(daysLate(impact)).toBe(5);
  });

  it('replaces IDs in reasons it has no sentence for, and strips warning codes', () => {
    expect(humanReason('missing_forecast: wi_permissions has no active accepted forecast', acme)).toContain('Permissions service has no accepted forecast');
    expect(plainWarning('supersedes_corrected: the note names DEC-12')).toBe('the note names DEC-12');
  });

  it('labels decisions for people', () => {
    expect(decisionLabel('DEC-13')).toBe('DEC-13');
    expect(decisionLabel('dec_baseline_wi_sso')).toBe('Baseline plan');
  });

  it('renders the Markdown subset without showing asterisks or backticks', () => {
    const { container } = render(<RichText text={'**Impact:** the `date_conflict` holds.\n- **Owner:** Priya'} />);
    expect(container.textContent).not.toMatch(/\*\*|`/);
    expect(screen.getByText('Impact:').tagName).toBe('STRONG');
    expect(container.querySelectorAll('li')).toHaveLength(1);
  });

  it('keeps numbered lists numbered', () => {
    const { container } = render(<RichText text={'1. First\n2. Second\n- Other'} />);
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
    expect(container.querySelectorAll('ul li')).toHaveLength(1);
  });
});

describe('source chips', () => {
  it('shows one titled chip per document and opens it with every quote', () => {
    const onOpen = vi.fn();
    render(<SourceTitles.Provider value={{ src_owners: 'Harbor ownership register' }}>
      <SourceChips onOpen={onOpen} citations={[{ source_id: 'src_owners', quote: 'Priya owns' }, { source_id: 'src_owners', quote: 'Maya is' }]} />
    </SourceTitles.Provider>);
    fireEvent.click(screen.getByRole('button', { name: /Harbor ownership register/ }));
    expect(onOpen).toHaveBeenCalledWith({ source_id: 'src_owners', quote: 'Priya owns', quotes: ['Priya owns', 'Maya is'] });
  });
});

describe('ripple graph', () => {
  const nodes = new Map<string, { id: string; label: string; kind: string }>(), edges = new Map<string, GraphView['edges'][number]>();
  for (const impact of changed) for (const path of impact.paths) {
    path.nodes.forEach(node => nodes.set(node.id, node));
    path.edges.forEach(edge => edges.set(`${edge.from_id}>${edge.to_id}`, edge));
  }
  const graph: GraphView = { evidence_version: 'v', nodes: [...nodes.values()], edges: [...edges.values()], removed_edges: [], queries: { impact_blockers: 'MATCH (k:Commitment)' } };

  it('marks the blocker and the promises it reaches, and leaves the rest clear', () => {
    const { container } = render(<RippleGraph graph={graph} impacts={changed} selectedId="com_acme_sso" changedIds={new Set()} busy={false} onSelect={vi.fn()} onToggle={vi.fn()} />);
    const state = (label: string) => [...container.querySelectorAll('.graph-node')].find(node => node.querySelector('title')?.textContent === label)?.getAttribute('class');
    expect(state('Permissions service')).toContain('node-blocker');
    expect(state('Acme')).toContain('node-hot');
    expect(state('Cedar')).toContain('node-clear');
    expect(container.querySelectorAll('.edge-hot').length).toBeGreaterThan(0);
  });

  it('cuts a dependency through the toggle and selects promises by clicking them', () => {
    const onToggle = vi.fn(), onSelect = vi.fn();
    render(<RippleGraph graph={graph} impacts={changed} selectedId={null} changedIds={new Set()} busy={false} onSelect={onSelect} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cut dependency: Identity migration depends on Permissions service' }));
    expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ from_id: 'wi_identity_migration', to_id: 'wi_permissions' }), false, 'Identity migration depends on Permissions service');
    fireEvent.click(screen.getByRole('button', { name: 'Open Birch' }));
    expect(onSelect).toHaveBeenCalledWith('com_birch_audit');
  });

  it('shows the impact Cypher on request', () => {
    render(<RippleGraph graph={graph} impacts={changed} selectedId={null} changedIds={new Set()} busy={false} onSelect={vi.fn()} onToggle={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Show the Cypher/ }));
    expect(screen.getByLabelText('Impact detection Cypher')).toHaveTextContent('MATCH (k:Commitment)');
  });
});
