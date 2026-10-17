import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import DemoControls from '../components/DemoControls';
import { setDemoScenario } from '../mocks/transport';
vi.mock('../mocks/transport', () => ({ setDemoScenario: vi.fn() }));

it('checks for unsaved edits before changing development fixture state', () => {
  const beforeChange = vi.fn().mockReturnValue(false), onChange = vi.fn();
  render(<DemoControls disabled={false} onChange={onChange} onBeforeChange={beforeChange} />);
  fireEvent.change(screen.getByLabelText('Sample state'), { target: { value: 'changed' } });
  expect(beforeChange).toHaveBeenCalledOnce();
  expect(setDemoScenario).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
});
