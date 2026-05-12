import { useEffect, useState, useRef } from 'react';
import { useLiveEvents } from '../hooks/useLiveEvents';

const DIRECTION_COLOR = {
  long: 'bg-green-100 text-green-700',
  short: 'bg-red-100 text-red-700',
  flat: 'bg-gray-100 text-gray-600',
};

function toDisplaySignal(raw) {
  // Normalise both DB rows and WebSocket event payloads to the same shape.
  return {
    _id: raw._id ?? raw.id ?? (raw.timestamp + raw.symbol),
    timestamp: raw.timestamp,
    symbol: raw.symbol,
    strategy_name: raw.strategy_name,
    direction: raw.direction,
    entry_price: raw.entry_price,
    stop_loss: raw.stop_loss,
    take_profit: raw.take_profit,
    confidence: raw.confidence ?? 1,
    regime: raw.regime,
  };
}

export function SignalsFeed() {
  const { events } = useLiveEvents();
  const [dbSignals, setDbSignals] = useState([]);
  const seenIds = useRef(new Set());

  // Load persisted signals from DB on mount
  useEffect(() => {
    fetch('/api/signals?limit=200')
      .then(r => r.json())
      .then(d => {
        const rows = (d.signals || []).map(s => {
          seenIds.current.add(s.id);
          return toDisplaySignal(s);
        });
        setDbSignals(rows);
      })
      .catch(() => {});
  }, []);

  // Merge live WebSocket signals that aren't already in the DB list
  const liveSignals = events
    .filter(e => e.event_type === 'signal_generated')
    .map(e => {
      const p = e.payload || {};
      return toDisplaySignal({ ...p, _id: e._id, timestamp: e.timestamp });
    })
    .filter(s => !seenIds.current.has(s._id));

  // Newest first; live signals arrive before DB catches up, so prepend them
  const signals = [...liveSignals, ...dbSignals];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Signals Feed</h1>
        <span className="text-sm text-gray-400">{signals.length} signal(s)</span>
      </div>

      <div className="bg-white rounded-xl shadow p-5 flex flex-col gap-3 max-h-[70vh] overflow-y-auto">
        {signals.length === 0 ? (
          <p className="text-gray-400 text-sm">No signals yet.</p>
        ) : (
          signals.map((s) => {
            const dir = s.direction || 'flat';
            const conf = s.confidence ?? 0;
            return (
              <div key={s._id} className="border rounded-lg p-3 flex flex-col gap-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm">{s.symbol}</span>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${DIRECTION_COLOR[dir] || DIRECTION_COLOR.flat}`}>
                    {dir.toUpperCase()}
                  </span>
                  <span className="text-xs text-gray-500">{s.strategy_name}</span>
                  <span className="text-xs text-gray-400 ml-auto">
                    {s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : ''}
                  </span>
                </div>
                <div className="flex gap-4 text-xs text-gray-600 flex-wrap">
                  {s.entry_price && <span>Entry: ${Number(s.entry_price).toFixed(2)}</span>}
                  {s.stop_loss && <span>SL: ${Number(s.stop_loss).toFixed(2)}</span>}
                  {s.take_profit && <span>TP: ${Number(s.take_profit).toFixed(2)}</span>}
                  {s.regime && <span>Regime: {s.regime}</span>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">Confidence</span>
                  <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                    <div className="bg-indigo-500 h-1.5 rounded-full" style={{ width: `${conf * 100}%` }} />
                  </div>
                  <span className="text-xs text-gray-500">{(conf * 100).toFixed(0)}%</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}