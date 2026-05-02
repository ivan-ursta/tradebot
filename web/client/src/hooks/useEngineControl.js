import { useState, useEffect, useCallback } from 'react';

export function useEngineControl() {
  const [processRunning, setProcessRunning] = useState(false);
  const [mode, setMode] = useState('paper');
  const [exchange, setExchange] = useState('binance');
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [statusRes, modeRes] = await Promise.all([
        fetch('/api/control/status'),
        fetch('/api/control/mode'),
      ]);
      const status = await statusRes.json();
      const modeData = await modeRes.json();
      setProcessRunning(status.running);
      setMode(modeData.mode);
      setLiveEnabled(modeData.live_enabled);
      setExchange(modeData.exchange || 'binance');
    } catch {
      // bridge offline — stay with last known state
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const start = useCallback(async (requestedMode) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/control/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: requestedMode }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to start');
      setProcessRunning(true);
      setMode(requestedMode);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const stop = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await fetch('/api/control/stop', { method: 'POST' });
      setProcessRunning(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  return { processRunning, mode, exchange, liveEnabled, loading, error, start, stop, refresh };
}