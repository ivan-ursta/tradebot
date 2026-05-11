import { useState, useEffect, useCallback } from 'react';

async function fetchSymbols() {
  try {
    const r = await fetch('/api/symbols');
    if (!r.ok) return [];
    const data = await r.json();
    return data.symbols ?? [];
  } catch {
    return [];
  }
}

export function TradingMarkets() {
  const [symbols, setSymbols] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    const s = await fetchSymbols();
    setSymbols(s);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleAdd() {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/symbols/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym }),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.error ?? 'Failed to add symbol');
        return;
      }
      if (data.reason === 'already_active') {
        setError(`${sym} is already being traded`);
      } else {
        setInput('');
        await refresh();
      }
    } catch {
      setError('Network error — is the engine running?');
    } finally {
      setLoading(false);
    }
  }

  async function handleRemove(sym) {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/symbols/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym }),
      });
      if (r.ok) await refresh();
    } catch {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      <h1 className="text-xl font-bold text-gray-800">Trading Markets</h1>

      <div className="bg-white rounded-xl shadow p-5">
        <div className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-3">
          Add Symbol
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Enter the exchange symbol to start trading (e.g. <span className="font-mono">SOL</span> for Hyperliquid, <span className="font-mono">SOLUSDT</span> for Binance).
        </p>
        <div className="flex gap-2">
          <input
            className="border border-gray-300 rounded px-3 py-1.5 text-sm flex-1 font-mono uppercase focus:outline-none focus:ring-2 focus:ring-indigo-400"
            placeholder="e.g. SOL"
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            disabled={loading}
          />
          <button
            onClick={handleAdd}
            disabled={loading || !input.trim()}
            className="bg-indigo-600 text-white text-sm px-4 py-1.5 rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            Start Trading
          </button>
        </div>
        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
      </div>

      <div className="bg-white rounded-xl shadow p-5">
        <div className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-3">
          Active Symbols
          <span className="ml-2 bg-gray-100 text-gray-600 rounded-full px-2 py-0.5 text-xs font-normal">
            {symbols.length}
          </span>
        </div>
        {symbols.length === 0 ? (
          <p className="text-gray-400 text-sm">No symbols currently being traded.</p>
        ) : (
          <div className="flex flex-col divide-y divide-gray-100">
            {symbols.map((sym) => (
              <div key={sym} className="flex items-center justify-between py-2.5 text-sm">
                <span className="font-mono font-medium text-gray-800">{sym}</span>
                <button
                  onClick={() => handleRemove(sym)}
                  disabled={loading}
                  className="text-xs px-3 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50 transition-colors"
                >
                  Stop
                </button>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-gray-400 mt-3">
          Stopping a symbol removes it from the next engine cycle but does not close open positions.
          Use the Positions page to close any open trades first.
        </p>
      </div>
    </div>
  );
}
