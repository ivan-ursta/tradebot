import { NavLink } from 'react-router-dom';
import { useEngineControl } from '../../hooks/useEngineControl';

const links = [
  { to: '/', label: 'Overview' },
  { to: '/markets', label: 'Markets' },
  { to: '/chart', label: 'Chart' },
  { to: '/positions', label: 'Positions' },
  { to: '/trades', label: 'Trade History' },
  { to: '/equity', label: 'Equity Chart' },
  { to: '/signals', label: 'Signals Feed' },
  { to: '/strategies', label: 'Strategies' },
  { to: '/config', label: 'Config' },
  { to: '/backtest', label: 'Backtest' },
  { to: '/settings', label: 'Settings' },
];

export function Sidebar() {
  const { processRunning, mode, exchange } = useEngineControl();

  const exchangeLabel = exchange === 'hyperliquid' ? 'HL' : 'BNB';
  const exchangeColor = exchange === 'hyperliquid' ? 'bg-yellow-700 text-yellow-100' : 'bg-yellow-600 text-yellow-100';

  return (
    <aside className="w-48 min-h-screen bg-gray-900 text-gray-200 flex flex-col py-6 px-3 shrink-0">
      <div className="text-lg font-bold text-white mb-2 px-2">TradeBot</div>

      {/* Engine status + badges */}
      <div className="flex items-center gap-1.5 px-2 mb-6 flex-wrap">
        <span className={`h-2 w-2 rounded-full shrink-0 ${processRunning ? 'bg-green-400' : 'bg-gray-500'}`} />
        <span className="text-xs text-gray-400 mr-auto">{processRunning ? 'Running' : 'Stopped'}</span>
        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${exchangeColor}`}>
          {exchangeLabel}
        </span>
        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${mode === 'live' ? 'bg-red-700 text-red-100' : 'bg-indigo-700 text-indigo-100'}`}>
          {mode === 'live' ? 'LIVE' : 'PAPER'}
        </span>
      </div>

      <nav className="flex flex-col gap-1">
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `px-3 py-2 rounded text-sm font-medium transition-colors ${
                isActive ? 'bg-indigo-600 text-white' : 'hover:bg-gray-700 text-gray-300'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}