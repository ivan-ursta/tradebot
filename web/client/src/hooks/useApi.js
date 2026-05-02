import { useCallback, useEffect, useRef, useState } from 'react';

export function useApi(url, intervalMs = 0) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(url);
      const json = await r.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    fetchData();
    if (intervalMs > 0) {
      timer.current = setInterval(fetchData, intervalMs);
    }
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [fetchData, intervalMs]);

  return { data, loading, error, refetch: fetchData };
}
