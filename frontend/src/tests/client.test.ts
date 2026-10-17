import { afterEach, describe, expect, it, vi } from 'vitest';
import { demoEnabled, request } from '../api/client';
afterEach(() => vi.unstubAllGlobals());
describe('live API boundary', () => {
  it('preserves an unavailable graph error and never substitutes sample impacts', async () => {
    expect(demoEnabled).toBe(false);
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'graph_unavailable', message: 'The graph cannot be reached.' } }), { status: 503 }));
    vi.stubGlobal('fetch', fetch);
    await expect(request('/impacts')).rejects.toMatchObject({ status: 503, code: 'graph_unavailable', message: 'The graph cannot be reached.' });
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0][0]).toBe('/api/impacts');
  });
  it('keeps network failure explicit so a mutation can retain its retry payload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/actions', { method: 'POST', body: '{}' })).rejects.toMatchObject({ status: 0, code: 'network_error' });
  });
});
