import type { AgentResponse } from '../api/types';
export function ToolTrace({ trace }: { trace: AgentResponse['tool_trace'] }) {
  if (!trace.length) return null;
  return <details className="tool-trace"><summary>Tool trace <span className="small muted">{trace.length} {trace.length === 1 ? 'call' : 'calls'}</span></summary><ol>{trace.map((call, i) => <li key={i}><div className="tool-heading"><code>{call.tool}</code><span>{call.status === 'ok' ? 'Completed' : 'Failed'}</span></div><pre>{JSON.stringify(call.arguments, null, 2)}</pre><p className="small muted">Evidence: {call.evidence_ids.join(', ') || 'None returned'}</p></li>)}</ol></details>;
}
