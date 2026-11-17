import { useCallback, useEffect, useRef, useState } from "react";

type Options = {
  /** Run load on mount (default true). */
  immediate?: boolean;
  /** Skip a second fetch within this window (Taro mount + useDidShow). */
  staleMs?: number;
};

export function useAsyncQuery<T>(loader: () => Promise<T>, deps: unknown[] = [], opts?: Options) {
  const immediate = opts?.immediate !== false;
  const staleMs = opts?.staleMs ?? 1600;
  const [data, setDataState] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState(false);
  const dataRef = useRef<T | null>(null);
  const lastAt = useRef(0);
  const inflight = useRef<Promise<T | null> | null>(null);
  const seq = useRef(0);

  const setData = useCallback((next: T | null) => {
    dataRef.current = next;
    lastAt.current = Date.now();
    setDataState(next);
  }, []);

  const reload = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && lastAt.current && now - lastAt.current < staleMs) {
      return dataRef.current;
    }
    if (!force && inflight.current) return inflight.current;
    const my = ++seq.current;
    if (dataRef.current == null) setLoading(true);
    setError(false);
    const run = (async () => {
      try {
        const result = await loader();
        if (my !== seq.current) return dataRef.current;
        dataRef.current = result;
        lastAt.current = Date.now();
        setDataState(result);
        return result;
      } catch {
        if (my !== seq.current) return dataRef.current;
        setError(true);
        dataRef.current = null;
        setDataState(null);
        return null;
      } finally {
        if (my === seq.current) {
          setLoading(false);
          inflight.current = null;
        }
      }
    })();
    inflight.current = run;
    return run;
  }, deps);

  useEffect(() => {
    if (immediate) void reload(true);
  }, [reload, immediate]);

  return { data, loading, error, reload, setData };
}
