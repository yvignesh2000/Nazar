import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Generic data-fetching hook with loading, error, and refetch support.
 * @param {Function} apiFn  - API function that returns a promise
 * @param {Array}    deps   - Dependency array for auto-refetch
 * @param {Object}   opts   - { enabled: true, initialData: null, onSuccess, onError }
 */
export function useApi(apiFn, deps = [], opts = {}) {
  const { enabled = true, initialData = null, onSuccess, onError } = opts;
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const execute = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const result = await apiFn();
      if (mountedRef.current) {
        setData(result);
        onSuccess?.(result);
      }
      return result;
    } catch (err) {
      if (mountedRef.current) {
        setError(err);
        onError?.(err);
      }
      throw err;
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [apiFn, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (enabled) execute();
  }, [execute, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error, refetch: execute, setData };
}

/**
 * Polling hook — calls apiFn on an interval.
 */
export function usePolling(apiFn, intervalMs = 30000, deps = []) {
  const { data, loading, error, refetch, setData } = useApi(apiFn, deps);

  useEffect(() => {
    if (intervalMs <= 0) return;
    const id = setInterval(refetch, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, refetch]);

  return { data, loading, error, refetch, setData };
}
