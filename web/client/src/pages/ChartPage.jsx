import { useState, useEffect, useRef, useCallback } from 'react';
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  HistogramSeries,
  LineStyle,
  CrosshairMode,
} from 'lightweight-charts';
import { useLiveEvents } from '../hooks/useLiveEvents';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];
const CANDLE_LIMITS = { '1m': 500, '5m': 500, '15m': 500, '1h': 500, '4h': 300, '1d': 200 };

// Convert ISO trade timestamp to Unix seconds snapped to candle boundary
function snapToCandle(isoTime, tfSeconds) {
  const ms = new Date(isoTime).getTime();
  return Math.floor(ms / 1000 / tfSeconds) * tfSeconds;
}

const TF_SECONDS = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 };

function buildMarkers(trades, timeframe) {
  const tfs = TF_SECONDS[timeframe] || 900;
  const markers = [];

  for (const t of trades) {
    if (!t.entry_time) continue;
    const isLong = t.side === 'long';
    const profit = (t.net_pnl ?? 0) >= 0;

    // Entry marker
    markers.push({
      time: snapToCandle(t.entry_time, tfs),
      position: isLong ? 'belowBar' : 'aboveBar',
      color: isLong ? '#26a69a' : '#ef5350',
      shape: isLong ? 'arrowUp' : 'arrowDown',
      text: `${isLong ? 'BUY' : 'SELL'} $${t.entry_price?.toFixed(2) ?? ''}`,
      size: 1,
    });

    // Exit marker (if closed)
    if (t.exit_time && t.exit_price) {
      const exitColor = profit ? '#26a69a' : '#ef5350';
      markers.push({
        time: snapToCandle(t.exit_time, tfs),
        position: isLong ? 'aboveBar' : 'belowBar',
        color: exitColor,
        shape: isLong ? 'arrowDown' : 'arrowUp',
        text: `${isLong ? 'SELL' : 'BUY'} $${t.exit_price.toFixed(2)} (${profit ? '+' : ''}$${(t.net_pnl ?? 0).toFixed(2)})`,
        size: 1,
      });
    }
  }

  // Sort by time (required by lightweight-charts)
  markers.sort((a, b) => a.time - b.time);

  // Deduplicate same-time same-position markers (take last)
  const seen = new Map();
  for (const m of markers) {
    seen.set(`${m.time}_${m.position}`, m);
  }
  return [...seen.values()].sort((a, b) => a.time - b.time);
}

function useCandles(symbol, timeframe) {
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const limit = CANDLE_LIMITS[timeframe] || 500;
      const res = await fetch(`/api/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to load candles');
      setCandles(data.candles || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  return { candles, loading, error, reload: load };
}

function useTrades(symbol) {
  const [trades, setTrades] = useState([]);
  useEffect(() => {
    fetch(`/api/trades?symbol=${symbol}&limit=200`)
      .then(r => r.json())
      .then(d => setTrades(d.trades || []))
      .catch(() => {});
  }, [symbol]);
  return trades;
}

const POPULAR_SYMBOLS = ['BTC', 'ETH', 'SOL', 'AVAX', 'BNB', 'SUI', 'DOGE', 'OP', 'ARB'];

export function ChartPage() {
  const [symbol, setSymbol] = useState('SOL');
  const [timeframe, setTimeframe] = useState('15m');
  const [whitelist, setWhitelist] = useState(['SOL', 'AVAX']);
  const [input, setInput] = useState('');

  const { snapshot, events } = useLiveEvents();
  const { candles, loading, error, reload } = useCandles(symbol, timeframe);
  const trades = useTrades(symbol);

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volSeriesRef = useRef(null);
  const priceLineRef = useRef(null);
  const markersRef = useRef(null);

  // Load whitelist from config (for badge highlighting only)
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(d => {
        const wl = d.config?.markets?.whitelist;
        if (wl?.length) setWhitelist(wl);
      })
      .catch(() => {});
  }, []);

  const goToSymbol = (s) => {
    const sym = s.trim().toUpperCase();
    if (sym) { setSymbol(sym); setInput(''); }
  };

  // Reload on fill events
  useEffect(() => {
    const fills = events.filter(e => e.event_type === 'order_filled' || e.event_type === 'position_closed');
    if (fills.length > 0) reload();
  }, [events, reload]);

  // Initialize chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#ffffff' },
        textColor: '#374151',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: '#f3f4f6' },
        horzLines: { color: '#f3f4f6' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#e5e7eb' },
      timeScale: {
        borderColor: '#e5e7eb',
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volSeriesRef.current = volSeries;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Update candle + volume data
  useEffect(() => {
    if (!candleSeriesRef.current || !volSeriesRef.current || !candles.length) return;

    candleSeriesRef.current.setData(candles);
    volSeriesRef.current.setData(
      candles.map(c => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(38,166,154,0.4)' : 'rgba(239,83,80,0.4)',
      }))
    );
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // Update trade markers (v5 API: createSeriesMarkers)
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const symbolTrades = trades.filter(t => t.symbol === symbol);
    const markers = buildMarkers(symbolTrades, timeframe);
    if (markersRef.current) {
      markersRef.current.setMarkers(markers);
    } else {
      markersRef.current = createSeriesMarkers(candleSeriesRef.current, markers);
    }
  }, [trades, symbol, timeframe]);

  // Update open-position price line
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    // Remove previous price line
    if (priceLineRef.current) {
      try { candleSeriesRef.current.removePriceLine(priceLineRef.current); } catch {}
      priceLineRef.current = null;
    }

    const pos = snapshot?.positions?.[symbol];
    if (pos && pos.avg_entry_price) {
      const isLong = pos.side === 'long';
      priceLineRef.current = candleSeriesRef.current.createPriceLine({
        price: pos.avg_entry_price,
        color: isLong ? '#26a69a' : '#ef5350',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `${isLong ? 'Long' : 'Short'} entry`,
      });
    }
  }, [snapshot, symbol]);

  const openPos = snapshot?.positions?.[symbol];
  const lastCandle = candles[candles.length - 1];

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Header controls */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-gray-800">Chart</h1>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Quick symbol buttons */}
          <div className="flex flex-wrap gap-1">
            {POPULAR_SYMBOLS.map(s => {
              const inWhitelist = whitelist.includes(s);
              const active = symbol === s;
              return (
                <button
                  key={s}
                  onClick={() => goToSymbol(s)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-md border transition-colors ${
                    active
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : inWhitelist
                        ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
                        : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                  }`}
                  title={inWhitelist ? 'In trading whitelist' : ''}
                >
                  {s}
                </button>
              );
            })}
          </div>

          {/* Custom symbol input */}
          <form
            onSubmit={e => { e.preventDefault(); goToSymbol(input); }}
            className="flex items-center gap-1"
          >
            <input
              value={input}
              onChange={e => setInput(e.target.value.toUpperCase())}
              placeholder="SYMBOL…"
              className="border border-gray-200 rounded-md px-2.5 py-1 text-xs w-24 focus:outline-none focus:ring-2 focus:ring-indigo-400 uppercase"
            />
            <button type="submit" className="px-2.5 py-1 text-xs rounded-md border border-gray-200 bg-white hover:bg-gray-50">→</button>
          </form>

          {/* Timeframe tabs */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            {TIMEFRAMES.map(tf => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${timeframe === tf ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              >
                {tf}
              </button>
            ))}
          </div>

          <button
            onClick={reload}
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
          >
            {loading ? '…' : '↻'}
          </button>
        </div>
      </div>

      {/* Position info bar */}
      {openPos && (
        <div className={`flex items-center gap-4 px-4 py-2 rounded-lg text-sm ${openPos.side === 'long' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
          <span className={`font-bold ${openPos.side === 'long' ? 'text-green-700' : 'text-red-700'}`}>
            {openPos.side?.toUpperCase()} {symbol}
          </span>
          <span className="text-gray-600">Entry: <strong>${openPos.avg_entry_price?.toFixed(2)}</strong></span>
          <span className="text-gray-600">Qty: <strong>{openPos.quantity?.toFixed(4)}</strong></span>
          <span className="text-gray-600">Notional: <strong>${openPos.notional_value?.toFixed(0)}</strong></span>
          <span className={`font-semibold ml-auto ${openPos.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {openPos.unrealized_pnl >= 0 ? '+' : ''}${openPos.unrealized_pnl?.toFixed(2)} unrealized
          </span>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error.includes('Bridge unreachable') || error.includes('503')
            ? 'Engine is not running — start it to load live candles.'
            : error}
        </div>
      )}

      {/* Chart container */}
      <div className="bg-white rounded-xl shadow flex-1 min-h-0 relative" style={{ minHeight: 420 }}>
        {loading && !candles.length && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-400 text-sm z-10 bg-white/80 rounded-xl">
            Loading candles…
          </div>
        )}
        <div ref={containerRef} className="w-full h-full rounded-xl" />
      </div>

      {/* Footer: last candle + legend */}
      <div className="flex items-center gap-4 text-xs text-gray-400 flex-wrap pb-1">
        {lastCandle && (
          <>
            <span>O <span className="text-gray-700">${lastCandle.open?.toFixed(2)}</span></span>
            <span>H <span className="text-green-600">${lastCandle.high?.toFixed(2)}</span></span>
            <span>L <span className="text-red-600">${lastCandle.low?.toFixed(2)}</span></span>
            <span>C <span className="text-gray-700 font-semibold">${lastCandle.close?.toFixed(2)}</span></span>
            <span>Vol <span className="text-gray-700">{lastCandle.volume?.toFixed(0)}</span></span>
          </>
        )}
        <span className="ml-auto">
          <span className="inline-block w-3 h-0.5 bg-green-500 mr-1" style={{ borderTop: '2px dashed #26a69a', display: 'inline-block', verticalAlign: 'middle' }} />
          Entry price line
        </span>
        <span>
          <span className="text-green-600 font-bold mr-1">▲</span>Buy
          <span className="text-red-600 font-bold mx-2">▼</span>Sell
        </span>
        <span>{candles.length} candles · auto-refresh 60s</span>
      </div>
    </div>
  );
}