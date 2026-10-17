export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) { super(message); this.name = 'ApiError'; }
}

export type Transport = (path: string, init?: RequestInit) => Promise<unknown>;
export const demoEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEMO === 'true';

const liveTransport: Transport = async (path, init) => {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_error', 'The request could not be completed. Check the connection and retry.');
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body?.error?.code || 'request_failed', body?.error?.message || `The server returned ${response.status}.`, body?.error?.details ?? body?.detail);
  }
  if (body === null) throw new ApiError(502, 'invalid_response', 'The server returned an unreadable response.');
  return body;
};

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // The production build removes this branch and the development fixture import.
  const transport = demoEnabled ? (await import('../mocks/transport')).demoTransport : liveTransport;
  return transport(path, init) as Promise<T>;
}

export const post = <T>(path: string, payload: unknown, signal?: AbortSignal) => request<T>(path, { method: 'POST', body: JSON.stringify(payload), signal });
export function errorMessage(error: unknown): string { return error instanceof Error ? error.message : 'Something went wrong. Please retry.'; }
export function isIdempotencyConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === 'idempotency_conflict';
}
export function needsFreshReview(error: unknown): boolean {
  if (isIdempotencyConflict(error)) return false;
  return error instanceof ApiError && [409, 410, 422].includes(error.status);
}
export function uncertainOutcome(error: unknown): boolean { return error instanceof ApiError && (error.status === 0 || error.status >= 500); }
