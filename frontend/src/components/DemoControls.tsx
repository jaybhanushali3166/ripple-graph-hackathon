import { setDemoScenario, type DemoScenario } from '../mocks/transport';
export default function DemoControls({ onChange, disabled }: { onChange: () => void; disabled: boolean }) {
  return <div className="demo-controls"><span><strong>Development demo</strong> · Scripted fixtures. Actions reset on reload or fixture change; no graph or model is connected.</span><label>Sample state<select value="" disabled={disabled} onChange={event => { setDemoScenario(event.target.value as DemoScenario); onChange(); }}><option value="" disabled>Load a fixture…</option><option value="baseline">Before update</option><option value="changed">After update</option><option value="missing_owner">Missing owner</option><option value="partial_ai">Partial AI result</option></select></label></div>;
}
