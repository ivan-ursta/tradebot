import { useLiveEvents } from '../hooks/useLiveEvents';
import { KillSwitchBanner } from '../components/layout/KillSwitchBanner';
import { EquityCard } from '../components/cards/EquityCard';
import { DrawdownGauge } from '../components/cards/DrawdownGauge';
import { StatCard } from '../components/cards/StatCard';

export function Overview() {
  const { snapshot } = useLiveEvents();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-bold text-gray-800">Overview</h1>

      {snapshot?.kill_switch_active && (
        <KillSwitchBanner reason={snapshot.kill_switch_reason} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <EquityCard
          equity={snapshot?.equity}
          startingEquity={snapshot?.starting_equity}
          dailyPnlPct={snapshot?.daily?.daily_pnl_pct}
        />
        <DrawdownGauge drawdown={snapshot?.current_drawdown} />
        <StatCard
          label="Open Positions"
          value={snapshot?.open_position_count ?? '—'}
          sub={`Exposure: ${snapshot ? (snapshot.total_exposure_fraction * 100).toFixed(1) : '—'}%`}
        />
        <StatCard
          label="Today's Trades"
          value={snapshot?.daily?.trade_count ?? '—'}
          sub={`Win rate: ${snapshot ? (snapshot.daily.win_rate * 100).toFixed(0) : '—'}%`}
        />
      </div>

      {snapshot && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-white rounded-xl shadow p-5">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Engine Status</div>
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Kill Switch</span>
                <span className={snapshot.kill_switch_active ? 'text-red-600 font-semibold' : 'text-green-600'}>
                  {snapshot.kill_switch_active ? 'ACTIVE' : 'OK'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Available Balance</span>
                <span className="font-medium">${snapshot.available_balance?.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Peak Equity</span>
                <span className="font-medium">${snapshot.peak_equity?.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Realized PnL (today)</span>
                <span className={`font-medium ${(snapshot.daily?.realized_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  ${snapshot.daily?.realized_pnl?.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow p-5">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Open Positions</div>
            {Object.keys(snapshot.positions || {}).length === 0 ? (
              <p className="text-gray-400 text-sm">No open positions</p>
            ) : (
              <div className="flex flex-col gap-2">
                {Object.values(snapshot.positions).map((p) => (
                  <div key={p.symbol} className="flex justify-between text-sm">
                    <span className="font-medium">{p.symbol}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${p.side === 'long' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {p.side?.toUpperCase()}
                    </span>
                    <span className="text-gray-600">${p.notional_value?.toFixed(0)}</span>
                    <span className={p.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                      {p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl?.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {!snapshot && (
        <div className="bg-white rounded-xl shadow p-8 text-center text-gray-400">
          Waiting for engine connection...
        </div>
      )}
    </div>
  );
}
