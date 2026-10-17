import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { useReviewedMutation } from '../hooks/useReviewedMutation';

describe('reviewed mutations', () => {
  it('retries an uncertain outcome with the exact original payload and key', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new ApiError(0, 'network_error', 'Connection lost')).mockResolvedValueOnce({ id: 'saved' });
    const { result } = renderHook(() => useReviewedMutation(submit));
    const original = { idempotency_key: 'stable-key', body: 'Reviewed text' };
    await act(async () => { await result.current.run(original).catch(() => {}); });
    expect(result.current.uncertain).toBe(true);
    await act(async () => { await result.current.run({ idempotency_key: 'accidental-new-key', body: 'Different text' }); });
    expect(submit).toHaveBeenNthCalledWith(2, original);
    expect(result.current.blocked).toBe(false);
  });
  it('prevents duplicate in-flight submissions even before a rerender', async () => {
    let finish!: (value: string) => void;
    const submit = vi.fn(() => new Promise<string>(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useReviewedMutation(submit));
    let first!: Promise<string | undefined>;
    act(() => { first = result.current.run({ idempotency_key: 'one' }); void result.current.run({ idempotency_key: 'two' }); });
    expect(submit).toHaveBeenCalledTimes(1);
    await act(async () => { finish('saved'); await first; });
  });
  it('clears uncertain state and allows a fresh submission after abandon()', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new ApiError(0, 'network_error', 'Connection lost')).mockResolvedValueOnce({ id: 'saved-fresh' });
    const { result } = renderHook(() => useReviewedMutation(submit));
    await act(async () => { await result.current.run({ idempotency_key: 'first-key', body: 'First' }).catch(() => {}); });
    expect(result.current.uncertain).toBe(true);
    expect(result.current.blocked).toBe(true);
    act(() => { result.current.abandon(); });
    expect(result.current.uncertain).toBe(false);
    expect(result.current.blocked).toBe(false);
    await act(async () => { await result.current.run({ idempotency_key: 'fresh-key', body: 'Fresh' }); });
    expect(submit).toHaveBeenNthCalledWith(2, { idempotency_key: 'fresh-key', body: 'Fresh' });
  });
});
