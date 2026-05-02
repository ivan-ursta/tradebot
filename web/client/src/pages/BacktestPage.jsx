import { useState, useEffect, useRef, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';

const SYMBOLS = ['SOL', 'AVAX', 'BTC', 'ETH'];

// Parse metric line: "[IN-SAMPLE  3000 bars]  Return=-2.11% | Sharpe=..."
function parseMetricLine(line) {
  const labelMatch = line.match(/\[(IN-SAMPLE|VALIDATION|OUT-OF-SAMPLE)[^\]]*\]/);
  if (!labelMatch) return null;
  const label = labelMatch[1];
  const extract = (key) => {
    const m = line.match(new RegExp(`${key}=([\\d.\\-]+)%?`));
    return m ? parseFloat(m[1]) : null;
  };
  return {
    label,
    return_pct: extract('Return'),
    sharpe: extract('Sharpe'),
    sortino: extract('Sortino'),
    max_dd: extract('MaxDD'),
    win_rate: extract('WinRate'),
    profit_factor: extract('PF'),
    trades: extract('Trades'),
  };
}

function MetricRow({ label, value, isPercent, good, bad }) {
  const num = parseFloat(value);
  const color = isNaN(num) ? '' : num >= good ? 'text-green-600' : num <= bad ? 'text-red-500' : 'text-yellow-600';
  return (
    <div className="flex justify-between py-1.5 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${color}`}>
        {isNaN(num) ? '—' : `${num.toFixed(2)}${isPercent ? '%' : ''}`}
      </span>
    </div>
  );
}

function MetricsCard({ title, m, highlight }) {
  if (!m) return null;
  return (
    <div className={`bg-white rounded-xl shadow p-4 ${highlight ? 'ring-2 ring-indigo-400' : ''}`}>
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">{title}</div>
      <MetricRow label="Return" value={m.return_pct} isPercent good={0} bad={-2} />
      <MetricRow label="Sharpe" value={m.sharpe} good={0.5} bad={0} />
      <MetricRow label="Win Rate" value={m.win_rate} isPercent good={40} bad={25} />
      <MetricRow label="Profit Factor" value={m.profit_factor} good={1.2} bad={1} />
      <MetricRow label="Max Drawdown" value={m.max_dd} isPercent good={-5} bad={-15} />
      <MetricRow label="Trades" value={m.trades} good={10} bad={3} />
    </div>
  );
}

export function BacktestPage() {
  const [symbol, setSymbol] = useState('SOL');
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [results, setResults] = useState(null);
  const [resultsError, setResultsError] = useState(null);
  const [availableSymbols, setAvailableSymbols] = useState([]);
  const logsRef = useRef(null);
  const pollRef = useRef(null);
  const logOffsetRef = useRef(0);

  useEffect(() => {
    fetch('/api/backtest/list')
      .then(r => r.json())
      .then(d => setAvailableSymbols(d.symbols || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  const loadResults = useCallback((sym) => {
    setResultsError(null);
    fetch(`/api/backtest/results/${sym}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setResultsError(d.error); setResults(null); return; }
        const equity = (d.equity || []).map(row => ({
          time: row[''] || row['timestamp'],
          equity: parseFloat(row['equity']),
        })).filter(r => !isNaN(r.equity));
        const trades = (d.trades || []).map(t => ({
          ...t,
          net_pnl: parseFloat(t.net_pnl),
          return_pct: parseFloat(t.return_pct) * 100,
        }));
        setResults({ equity, trades });
      })
      .catch(() => setResultsError('Failed to load results'));
  }, []);

  const pollStatus = useCallback((jobId, sym) => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/backtest/status/${jobId}?since=${logOffsetRef.current}`);
        const data = await res.json();

        if (data.logs?.length) {
          logOffsetRef.current += data.logs.length;
          setLogs(prev => {
            const next = [...prev, ...data.logs];
            const newMetrics = data.logs.map(parseMetricLine).filter(Boolean);
            if (newMetrics.length) setMetrics(pm => [...pm, ...newMetrics]);
            return next;
          });
        }

        if (!data.running) {
          setRunning(false);
          clearInterval(pollRef.current);
          loadResults(sym);
          setAvailableSymbols(prev => prev.includes(sym) ? prev : [...prev, sym]);
        }
      } catch {
        setRunning(false);
        clearInterval(pollRef.current);
      }
    };

    clearInterval(pollRef.current);
    pollRef.current = setInterval(poll, 2000);
    poll();
  }, [loadResults]);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const runBacktest = async () => {
    if (running) return;
    setRunning(true);
    setLogs([]);
    setMetrics([]);
    setResults(null);
    setResultsError(null);
    logOffsetRef.current = 0;

    try {
      const res = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      });
      const { jobId } = await res.json();
      pollStatus(jobId, symbol);
    } catch {
      setRunning(false);
    }
  };

  const inSample = metrics.find(m => m.label === 'IN-SAMPLE');
  const validation = metrics.find(m => m.label === 'VALIDATION');
  const outOfSample = metrics.find(m => m.label === 'OUT-OF-SAMPLE');

  const startEquity = results?.equity?.[0]?.equity ?? 10000;
  const endEquity = results?.equity?.[results.equity.length - 1]?.equity;
  const totalReturn = endEquity ? ((endEquity - startEquity) / startEquity * 100) : null;
  const winTrades = results?.trades?.filter(t => t.net_pnl > 0).length ?? 0;
  const totalTrades = results?.trades?.length ?? 0;

  return (
    <div className="flex flex-col gap-5 max-w-5xl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-gray-800">Backtest</h1>

        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            {SYMBOLS.map(s => (
              <button
                key={s}
                onClick={() => { setSymbol(s); if (availableSymbols.includes(s)) loadResults(s); }}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${symbol === s ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              >
                {s}
                {availableSymbols.includes(s) && s !== symbol && (
                  <span className="ml-1 text-xs text-green-500">✓</span>
                )}
              </button>
            ))}
          </div>
          <button
            onClick={runBacktest}
            disabled={running}
            className="px-4 py-1.5 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-2"
          >
            {running && <span className="animate-spin">⟳</span>}
            {running ? 'Running…' : 'Run Backtest'}
          </button>
        </div>
      </div>

      {/* Metrics cards */}
      {metrics.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <MetricsCard title="In-Sample (60%)" m={inSample} />
          <MetricsCard title="Validation (20%)" m={validation} />
          <MetricsCard title="Out-of-Sample (20%)" m={outOfSample} highlight />
        </div>
      )}

      {/* Equity curve */}
      {results?.equity?.length > 0 && (
        <div className="bg-white rounded-xl shadow p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
              OOS Equity Curve — {symbol}
            </span>
            <div className="flex items-center gap-4 text-sm">
              {totalReturn !== null && (
                <span className={totalReturn >= 0 ? 'text-green-600 font-semibold' : 'text-red-500 font-semibold'}>
                  {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
                </span>
              )}
              <span className="text-gray-400">{totalTrades} trades · {winTrades}W/{totalTrades - winTrades}L</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={results.equity} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="time" tick={false} />
              <YAxis domain={['auto', 'auto']} tickFormatter={v => `$${v.toFixed(0)}`} width={68} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => [`$${v.toFixed(2)}`, 'Equity']} labelFormatter={() => ''} />
              <ReferenceLine y={startEquity} stroke="#9ca3af" strokeDasharray="4 2" />
              <Line
                type="monotone"
                dataKey="equity"
                stroke={totalReturn >= 0 ? '#26a69a' : '#ef5350'}
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* OOS Trades table */}
      {results?.trades?.length > 0 && (
        <div className="bg-white rounded-xl shadow p-5">
          <div className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">OOS Trades</div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 uppercase border-b">
                  <th className="py-2 pr-4">Side</th>
                  <th className="py-2 pr-4">Entry</th>
                  <th className="py-2 pr-4">Exit</th>
                  <th className="py-2 pr-4">Net PnL</th>
                  <th className="py-2 pr-4">Return</th>
                  <th className="py-2">Exit reason</th>
                </tr>
              </thead>
              <tbody>
                {results.trades.map((t, i) => (
                  <tr key={i} className="border-b hover:bg-gray-50">
                    <td className="py-1.5 pr-4">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${t.side === 'long' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                        {t.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-1.5 pr-4">${parseFloat(t.entry_price).toFixed(3)}</td>
                    <td className="py-1.5 pr-4">${parseFloat(t.exit_price).toFixed(3)}</td>
                    <td className={`py-1.5 pr-4 font-medium ${t.net_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {t.net_pnl >= 0 ? '+' : ''}${t.net_pnl.toFixed(2)}
                    </td>
                    <td className={`py-1.5 pr-4 ${t.return_pct >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {t.return_pct >= 0 ? '+' : ''}{t.return_pct.toFixed(2)}%
                    </td>
                    <td className="py-1.5 text-gray-400 text-xs">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {resultsError && !running && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-500">
          {resultsError}
        </div>
      )}

      {/* Log output */}
      {logs.length > 0 && (
        <div className="bg-white rounded-xl shadow p-4">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Output</div>
          <div
            ref={logsRef}
            className="font-mono text-xs text-gray-600 bg-gray-50 rounded p-3 h-48 overflow-y-auto"
          >
            {logs.map((line, i) => {
              const isMetric = /\[(IN-SAMPLE|VALIDATION|OUT-OF-SAMPLE)/.test(line);
              const isWarn = line.includes('⚠') || line.includes('WARN');
              return (
                <div key={i} className={isMetric ? 'text-indigo-600 font-semibold' : isWarn ? 'text-yellow-600' : ''}>
                  {line}
                </div>
              );
            })}
            {running && <div className="text-gray-400 animate-pulse">running…</div>}
          </div>
        </div>
      )}
    </div>
  );
}