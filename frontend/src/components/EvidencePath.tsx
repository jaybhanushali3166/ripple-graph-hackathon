import { Box, Building2, Flag, Layers } from 'lucide-react';
import { useState } from 'react';
import type { EvidencePath as Path, SourceRef } from '../api/types';
import { SourceButton, type OpenSource } from './SourceButton';
export function EvidencePath({ paths, citations, onSource }: { paths: Path[]; citations?: SourceRef[]; onSource: OpenSource }) {
  const [index, setIndex] = useState(0);
  const path = paths[index] ?? paths[0];
  if (!path) return <p className="muted">No evidence path was returned. This commitment needs verification.</p>;
  return <section className="evidence-section" aria-label="Evidence path">
    <div className="section-heading"><h3>Why this commitment?</h3><span className="small muted">{path.edges.length} relationships</span></div>
    {paths.length > 1 && <label className="field-label">Evidence path<select value={index} onChange={event => setIndex(Number(event.target.value))}>{paths.map((_, i) => <option key={i} value={i}>Path {i + 1} of {paths.length}</option>)}</select></label>}
    <ol className="evidence-chain">{path.nodes.map((node, i) => {
      const Icon = node.kind === 'customer' ? Building2 : node.kind === 'commitment' ? Flag : i === path.nodes.length - 1 ? Layers : Box;
      const edges = path.edges.filter(edge => edge.from_id === node.id);
      return <li key={`${node.id}:${i}`} className="evidence-node"><span className="node-icon"><Icon size={13} aria-hidden="true" /></span><div><div className="node-label">{node.label}</div>{edges.map(edge => {
        const citation = citations?.find(c => c.source_id === edge.source_id);
        const sourceRef = citation ? { source_id: edge.source_id, quote: citation.quote } : { source_id: edge.source_id };
        return <div className="evidence-edge" key={`${edge.from_id}:${edge.to_id}`}><span>{edge.relation.toLowerCase().replaceAll('_', ' ')}</span><SourceButton source={sourceRef} onOpen={onSource} /></div>;
      })}</div></li>;
    })}</ol>
  </section>;
}
