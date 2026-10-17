import { useRef, useState } from 'react';
import { uncertainOutcome } from '../api/client';

// Keep a mutation's immutable payload/key across uncertain network outcomes.
export function useReviewedMutation<Payload, Result>(submit: (payload: Payload) => Promise<Result>) {
  const attempt = useRef<Payload | null>(null), pendingRef = useRef(false);
  const [pending, setPending] = useState(false), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function run(payload?: Payload): Promise<Result | undefined> {
    if (pendingRef.current) return;
    const next = attempt.current ?? payload;
    if (!next) return;
    attempt.current = next; pendingRef.current = true; setPending(true); setError(null);
    try {
      const result = await submit(next);
      attempt.current = null; setUncertain(false); return result;
    } catch (cause) {
      const unknown = uncertainOutcome(cause);
      if (!unknown) attempt.current = null;
      setUncertain(unknown); setError(cause); throw cause;
    } finally { pendingRef.current = false; setPending(false); }
  }
  return { run, pending, uncertain, error, blocked: pending || uncertain };
}
