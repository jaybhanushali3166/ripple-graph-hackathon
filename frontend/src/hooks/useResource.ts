import { useEffect, useRef, useState } from 'react';

type Resource<T> = { key: string | null; data: T | null; error: unknown; loading: boolean };
export function useResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const loader = useRef(load); loader.current = load;
  const [state, setState] = useState<Resource<T>>({ key: null, data: null, error: null, loading: false });
  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setState({ key, data: null, error: null, loading: true });
    loader.current(controller.signal).then(
      data => { if (!controller.signal.aborted) setState({ key, data, error: null, loading: false }); },
      error => { if (!controller.signal.aborted) setState({ key, data: null, error, loading: false }); },
    );
    return () => controller.abort();
  }, [key]);
  return state.key === key ? state : { key, data: null, error: null, loading: key !== null };
}
