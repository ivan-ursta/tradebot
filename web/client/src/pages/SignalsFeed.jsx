import { useLiveEvents } from '../hooks/useLiveEvents';

const DIRECTION_COLOR = {
  long: 'bg-green-100 text-green-700',
  short: 'bg-red-100 text-red-700',
  flat: 'bg-gray-100 text-gray-600',
};

export function SignalsFeed() {
  const { events } = useLiveEvents();

  const signals = events
    .filter((e) => e.event_type === 'signal_generated')
    .slice()
    .reverse();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Signals Feed</h1>
        <span className="text-sm text-gray-400">{signals.length} signal(s) this session</span>
      </div>

      <div className="bg-white rounded-xl shadow p-5 flex flex-col gap-3 max-h-[70vh] overflow-y-auto">
        {signals.length === 0 ? (
          <p className="text-gray-400 text-sm">Waiting for signals...</p>
        ) : (
          signals.map((e) => {
            const s = e.payload || {};
            const dir = s.direction || 'flat';
            const conf = s.confidence ?? 0;
            return (
              <div key={e._id} className="border rounded-lg p-3 flex flex-col gap-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm">{s.symbol}</span>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${DIRECTION_COLOR[dir] || DIRECTION_COLOR.flat}`}>
                    {dir.toUpperCase()}
                  </span>
                  <span className="text-xs text-gray-500">{s.strategy_name}</span>
                  <span className="text-xs text-gray-400 ml-auto">
                    {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ''}
                  </span>
                </div>
                <div className="flex gap-4 text-xs text-gray-600 flex-wrap">
                  {s.entry_price && <span>Entry: ${s.entry_price.toFixed(2)}</span>}
                  {s.stop_loss && <span>SL: ${s.stop_loss.toFixed(2)}</span>}
                  {s.take_profit && <span>TP: ${s.take_profit.toFixed(2)}</span>}
                  <span>Regime: {s.regime}</span>
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
