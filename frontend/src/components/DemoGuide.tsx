import { Check, RotateCcw, X } from 'lucide-react';
import { useState } from 'react';

const KEY = 'ripple.demoGuide.hidden';
function readHidden() { try { return localStorage.getItem(KEY) === '1'; } catch { return false; } }
function writeHidden() { try { localStorage.setItem(KEY, '1'); } catch { /* per-viewer convenience only */ } }

/** A four-step walkthrough of the live demo; each step ticks from the real graph state. */
export function DemoGuide({ conflicts, cutEdges, busy, onReset }: { conflicts: number; cutEdges: number; busy: boolean; onReset: () => void }) {
  const [hidden, setHidden] = useState(readHidden);
  if (hidden) return null;
  const steps = [
    { title: 'Start clean', body: 'Reset the shared demo. Every promise is on track.', done: conflicts === 0 && cutEdges === 0 },
    { title: 'Log the slip', body: 'Click Review decision, use the sample note, confirm.', done: conflicts > 0 },
    { title: 'Follow the ripple', body: 'Acme and Birch turn red. Cedar and Delta stay clear.', done: conflicts > 0 },
    { title: 'Prove it is the graph', body: 'Cut Identity migration → Permissions. Acme clears.', done: cutEdges > 0 },
  ];
  return <section className="demo-guide" aria-label="Demo walkthrough">
    <div className="demo-guide-head">
      <span className="eyebrow">Try the 60-second demo</span>
      <div className="demo-guide-actions">
        <button type="button" className="button small" disabled={busy} onClick={onReset}><RotateCcw size={13} aria-hidden="true" />Reset demo</button>
        <button type="button" className="button button-quiet button-icon" aria-label="Hide walkthrough" onClick={() => { writeHidden(); setHidden(true); }}><X size={14} aria-hidden="true" /></button>
      </div>
    </div>
    <ol className="demo-steps">{steps.map((step, i) => <li key={step.title} className={step.done ? 'step-done' : ''}>
      <span className="step-mark" aria-hidden="true">{step.done ? <Check size={12} /> : i + 1}</span>
      <div><strong>{step.title}</strong><span>{step.body}</span></div>
    </li>)}</ol>
  </section>;
}
