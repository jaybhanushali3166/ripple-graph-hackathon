import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useResource } from '../hooks/useResource';

describe('selection-scoped reads', () => {
  it('does not let a late Acme result overwrite the newer Birch selection', async () => {
    const resolve: Record<string, (value: string) => void> = {};
    const { result, rerender } = renderHook(({ id }) => useResource(id, () => new Promise<string>(done => { resolve[id] = done; })), { initialProps: { id: 'acme' } });
    rerender({ id: 'birch' });
    await act(async () => resolve.birch('Birch evidence'));
    await waitFor(() => expect(result.current.data).toBe('Birch evidence'));
    await act(async () => resolve.acme('Old Acme evidence'));
    expect(result.current.data).toBe('Birch evidence');
  });
});
