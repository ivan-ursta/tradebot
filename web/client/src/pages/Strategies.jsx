import { useApi } from '../hooks/useApi';

export function Strategies() {
  const { data, loading } = useApi('/api/strategies', 10000);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold text-gray-800">Strategies</h1>
      <div className="bg-white rounded-xl shadow p-5">
        {loading && <p className="text-gray-400 text-sm">Loading...</p>}
        {data && data.strategies.length === 0 && (
          <p className="text-gray-400 text-sm">No active strategies (engine offline?)</p>
        )}
        {data && data.strategies.map((s) => (
          <div key={s.name} className="border rounded-lg p-4 mb-3">
            <div className="flex items-center gap-3 mb-2">
              <span className="font-semibold">{s.name}</span>
              {s.in_cooldown ? (
                <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 text-yellow-700">Cooldown</span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">Active</span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
              <div>Consecutive losses: <span className="font-medium">{s.consecutive_losses}</span></div>
              {s.cooldown_until && (
                <div>Cooldown until: <span className="font-medium">{new Date(s.cooldown_until).toLocaleTimeString()}</span></div>
              )}
            </div>
          </div>
        ))}
        {data && Object.keys(data.regimes || {}).length > 0 && (
          <div className="mt-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Market Regimes</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.regimes).map(([sym, reg]) => (
                <span key={sym} className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700 font-mono">
                  {sym}: {reg}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
