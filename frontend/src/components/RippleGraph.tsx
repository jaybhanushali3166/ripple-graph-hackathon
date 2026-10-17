import { Code2, Scissors, Undo2 } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import type { GraphEdge, GraphView, Impact } from '../api/types';
import { shortDate } from '../lib/dates';
import { daysLate, lateLabel } from '../lib/reasons';

const COL_W = 210, NODE_W = 168, NODE_H = 46, ROW_H = 64, PAD_X = 16, PAD_Y = 28;
const KIND_LABEL: Record<string, string> = { customer: 'Customer', commitment: 'Promise', feature: 'Feature', project: 'Project', component: 'Component' };
const COLUMN_TITLES = ['Customers', 'Promises', 'Features', 'Dependencies', 'Upstream', 'Upstream'];

type Placed = { id: string; label: string; kind: string; col: number; x: number; y: number };

/** Layered left-to-right layout: customers, promises, then work items by dependency depth. */
function layout(graph: GraphView, impacts: Impact[]) {
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const edges = graph.edges.filter(edge => nodes.has(edge.from_id) && nodes.has(edge.to_id));
  const removed = graph.removed_edges.filter(edge => nodes.has(edge.from_id) && nodes.has(edge.to_id));
  const col = new Map<string, number>();
  for (const node of graph.nodes) {
    if (node.kind === 'customer') col.set(node.id, 0);
    else if (node.kind === 'commitment') col.set(node.id, 1);
  }
  for (const edge of edges) if (edge.relation === 'REQUIRES') col.set(edge.to_id, Math.max(col.get(edge.to_id) ?? 2, 2));
  for (const node of graph.nodes) if (!col.has(node.id)) col.set(node.id, 2);
  // Removed edges still shape the layout so cutting one doesn't make the picture jump.
  const dependsOn = [...edges, ...removed].filter(edge => edge.relation === 'DEPENDS_ON');
  for (let pass = 0; pass < graph.nodes.length; pass++) {
    let moved = false;
    for (const edge of dependsOn) {
      const next = (col.get(edge.from_id) ?? 2) + 1;
      if (next > (col.get(edge.to_id) ?? 2)) { col.set(edge.to_id, next); moved = true; }
    }
    if (!moved) break;
  }

  const customerOrder = [...new Set(impacts.map(impact => impact.customer.id))];
  const commitmentOrder = impacts.map(impact => impact.commitment_id);
  const columns: string[][] = [];
  for (const [id, c] of col) (columns[c] ??= []).push(id);
  const rank = new Map<string, number>();
  const parents = (id: string) => [...edges, ...removed].filter(edge => edge.to_id === id).map(edge => rank.get(edge.from_id)).filter((r): r is number => r !== undefined);
  columns.forEach((ids, c) => {
    const key = (id: string) => c === 0 ? customerOrder.indexOf(id) : c === 1 ? commitmentOrder.indexOf(id) : (parents(id).reduce((a, b) => a + b, 0) / Math.max(1, parents(id).length));
    ids.sort((a, b) => key(a) - key(b) || a.localeCompare(b)).forEach((id, i) => rank.set(id, i));
  });
  const rows = Math.max(...columns.map(ids => ids?.length ?? 0));
  const height = PAD_Y * 2 + rows * ROW_H;
  const placed = new Map<string, Placed>();
  columns.forEach((ids, c) => ids?.forEach((id, i) => {
    const node = nodes.get(id)!;
    const offset = (rows - ids.length) * ROW_H / 2;
    placed.set(id, { ...node, col: c, x: PAD_X + c * COL_W, y: PAD_Y + offset + i * ROW_H + (ROW_H - NODE_H) / 2 });
  }));
  return { placed, edges, removed, height, width: PAD_X * 2 + (columns.length - 1) * COL_W + NODE_W, columns: columns.length };
}

function curve(from: Placed, to: Placed) {
  const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2, x2 = to.x, y2 = to.y + NODE_H / 2, mid = (x1 + x2) / 2;
  return { d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, mx: mid, my: (y1 + y2) / 2 };
}

const edgeKey = (edge: GraphEdge) => `${edge.from_id}>${edge.to_id}`;
const truncate = (text: string, max = 22) => text.length > max ? `${text.slice(0, max - 1)}…` : text;

export function RippleGraph({ graph, impacts, selectedId, changedIds, busy, onSelect, onToggle }: {
  graph: GraphView;
  impacts: Impact[];
  selectedId: string | null;
  changedIds: Set<string>;
  busy: boolean;
  onSelect: (commitmentId: string) => void;
  onToggle: (edge: GraphEdge, present: boolean, label: string) => void;
}) {
  const [showQuery, setShowQuery] = useState(false);
  const view = useMemo(() => layout(graph, impacts), [graph, impacts]);
  const byCommitment = new Map(impacts.map(impact => [impact.commitment_id, impact]));
  // A customer opens its most urgent promise: a conflict first, else the earliest due.
  const customerOf = new Map<string, Impact>();
  for (const impact of [...impacts].sort((a, b) => Number(b.status === 'date_conflict') - Number(a.status === 'date_conflict') || a.due_at - b.due_at)) {
    if (!customerOf.has(impact.customer.id)) customerOf.set(impact.customer.id, impact);
  }

  // The ripple: every node and edge on a path from a conflicting promise to its blocker.
  const hotNodes = new Set<string>(), hotEdges = new Set<string>(), blockers = new Map<string, number>();
  const selectedNodes = new Set<string>(), selectedEdges = new Set<string>();
  for (const impact of impacts) {
    const blockerIds = new Set(impact.blockers.map(blocker => blocker.work_item_id));
    for (const blocker of impact.blockers) blockers.set(blocker.work_item_id, blocker.available_at);
    for (const path of impact.paths) {
      const ids = path.nodes.map(node => node.id);
      const end = ids.findIndex(id => blockerIds.has(id));
      if (impact.commitment_id === selectedId) {
        ids.forEach(id => selectedNodes.add(id));
        path.edges.forEach(edge => selectedEdges.add(edgeKey(edge)));
      }
      if (impact.status !== 'date_conflict' || end < 0) continue;
      ids.slice(0, end + 1).forEach(id => hotNodes.add(id));
      path.edges.slice(0, end).forEach(edge => hotEdges.add(edgeKey(edge)));
    }
  }
  const freshEdges = new Set<string>();
  for (const id of changedIds) {
    const impact = byCommitment.get(id);
    impact?.paths.forEach(path => path.edges.forEach(edge => { if (hotEdges.has(edgeKey(edge))) freshEdges.add(edgeKey(edge)); }));
  }

  const nodeState = (node: Placed) => {
    const commitment = node.kind === 'commitment' ? byCommitment.get(node.id) : node.kind === 'customer' ? customerOf.get(node.id) : undefined;
    if (blockers.has(node.id)) return 'blocker';
    if (hotNodes.has(node.id)) return 'hot';
    if (commitment && commitment.status === 'needs_verification') return 'verify';
    if (commitment) return 'clear';
    return 'idle';
  };
  const subtitle = (node: Placed) => {
    if (blockers.has(node.id)) return `Forecast ${shortDate(blockers.get(node.id)!)}`;
    if (node.kind === 'commitment') {
      const impact = byCommitment.get(node.id);
      const late = impact ? daysLate(impact) : null;
      return impact ? `Due ${shortDate(impact.due_at)}${late !== null ? ` · ${lateLabel(late)}` : ''}` : KIND_LABEL.commitment;
    }
    return KIND_LABEL[node.kind] ?? node.kind;
  };
  const selectNode = (node: Placed) => {
    const id = node.kind === 'commitment' ? node.id : node.kind === 'customer' ? customerOf.get(node.id)?.commitment_id : undefined;
    if (id) onSelect(id);
  };
  const keyed = (action: () => void) => (event: KeyboardEvent) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); } };
  const edgeLabel = (edge: GraphEdge) => `${view.placed.get(edge.from_id)?.label} depends on ${view.placed.get(edge.to_id)?.label}`;

  const conflicts = impacts.filter(impact => impact.status === 'date_conflict');
  return <section className="ripple-graph" aria-label="Dependency graph">
    <div className="graph-heading">
      <div>
        <h2>The ripple map</h2>
        <p className="muted small">{conflicts.length
          ? `${[...blockers.keys()].map(id => view.placed.get(id)?.label).join(', ')} slipped. The red path is how that reaches ${conflicts.map(impact => impact.customer.name).join(' and ')}.`
          : 'Live from FalkorDB. Every promise traced to the work it depends on. No path is late right now.'}</p>
      </div>
      <div className="graph-legend" aria-hidden="true">
        <span><i className="legend-dot legend-blocker" />Slipped work</span>
        <span><i className="legend-dot legend-hot" />Promise at risk</span>
        <span><i className="legend-dot legend-clear" />On track</span>
        <span><Scissors size={11} />Cut a dependency</span>
      </div>
    </div>
    <div className="graph-scroll">
      <svg viewBox={`0 0 ${view.width} ${view.height}`} width={view.width} height={view.height} role="group" aria-label={`Dependency graph: ${graph.nodes.length} nodes and ${view.edges.length} relationships`}>
        {Array.from({ length: view.columns }, (_, c) => <text key={c} className="column-title" x={PAD_X + c * COL_W} y={14}>{COLUMN_TITLES[c] ?? ''}</text>)}
        {view.removed.map(edge => {
          const from = view.placed.get(edge.from_id), to = view.placed.get(edge.to_id);
          if (!from || !to) return null;
          const { d, mx, my } = curve(from, to);
          return <g key={`removed:${edgeKey(edge)}`}>
            <path d={d} className="edge edge-removed" />
            <g className={`edge-toggle edge-toggle-restore${busy ? ' is-busy' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-label={`Restore dependency: ${edgeLabel(edge)}`}
              onClick={() => !busy && onToggle(edge, true, edgeLabel(edge))} onKeyDown={keyed(() => !busy && onToggle(edge, true, edgeLabel(edge)))}>
              <title>Restore this recorded dependency</title>
              <circle cx={mx} cy={my} r={11} /><Undo2 x={mx - 6} y={my - 6} width={12} height={12} />
            </g>
          </g>;
        })}
        {view.edges.map(edge => {
          const from = view.placed.get(edge.from_id), to = view.placed.get(edge.to_id);
          if (!from || !to) return null;
          const { d, mx, my } = curve(from, to);
          const key = edgeKey(edge);
          const cls = ['edge', hotEdges.has(key) && 'edge-hot', freshEdges.has(key) && 'edge-fresh', selectedEdges.has(key) && 'edge-selected'].filter(Boolean).join(' ');
          return <g key={key}>
            <path d={d} className={cls} />
            {edge.relation === 'DEPENDS_ON' && <g className={`edge-toggle${busy ? ' is-busy' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-label={`Cut dependency: ${edgeLabel(edge)}`}
              onClick={() => !busy && onToggle(edge, false, edgeLabel(edge))} onKeyDown={keyed(() => !busy && onToggle(edge, false, edgeLabel(edge)))}>
              <title>Cut this dependency to see the graph recompute impact</title>
              <circle cx={mx} cy={my} r={11} /><Scissors x={mx - 6} y={my - 6} width={12} height={12} />
            </g>}
          </g>;
        })}
        {[...view.placed.values()].map(node => {
          const state = nodeState(node);
          const clickable = node.kind === 'commitment' || node.kind === 'customer';
          const selected = selectedNodes.has(node.id) && clickable;
          return <g key={node.id} className={`graph-node node-${state}${selected ? ' node-selected' : ''}${clickable ? ' node-clickable' : ''}`}
            transform={`translate(${node.x},${node.y})`}
            {...(clickable ? { role: 'button', tabIndex: 0, 'aria-label': `Open ${node.label}`, onClick: () => selectNode(node), onKeyDown: keyed(() => selectNode(node)) } : {})}>
            <title>{node.label}</title>
            <rect width={NODE_W} height={NODE_H} rx={7} />
            <text className="node-title" x={12} y={19}>{truncate(node.label)}</text>
            <text className="node-sub" x={12} y={35}>{subtitle(node)}</text>
          </g>;
        })}
      </svg>
    </div>
    <div className="graph-footer">
      <p className="small muted">Impact is computed by a Cypher traversal over these edges, not drawn on top. Cut the edge into a slipped dependency and its promise clears; restore it and the flag returns.</p>
      <button type="button" className="text-button" onClick={() => setShowQuery(value => !value)} aria-expanded={showQuery}><Code2 size={13} aria-hidden="true" />{showQuery ? 'Hide' : 'Show'} the Cypher</button>
    </div>
    {showQuery && <pre className="cypher-block" aria-label="Impact detection Cypher">{graph.queries.impact_blockers ?? ''}</pre>}
  </section>;
}
