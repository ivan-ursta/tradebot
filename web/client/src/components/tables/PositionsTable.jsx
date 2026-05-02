import { useState } from 'react';

async function closePosition(symbol, onDone) {
  try {
    const r = await fetch(`/api/control/close/${symbol}`, { method: 'POST' });
    const data = await r.json();
    if (data.closed) onDone?.();
    else alert(data.error || 'Close failed');
  } catch {
    alert('Network error');
  }
}

export function PositionsTable({ positions, onClose }) {
  const [closing, setClosing] = useState(null);

  if (!positions || positions.length === 0) {
    return <p className="text-gray-400 text-sm py-4">No open positions</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b text-xs uppercase">
            <th className="py-2 pr-4">Symbol</th>
            <th className="py-2 pr-4">Side</th>
            <th className="py-2 pr-4">Qty</th>
            <th className="py-2 pr-4">Entry</th>
            <th className="py-2 pr-4">Notional</th>
            <th className="py-2 pr-4">Unrealized PnL</th>
            <th className="py-2 pr-4">Strategy</th>
            <th className="py-2">Action</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const pnl = p.unrealized_pnl ?? 0;
            const pnlClass = pnl >= 0 ? 'text-green-600' : 'text-red-600';
            return (
              <tr key={p.symbol} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4 font-semibold">{p.symbol}</td>
                <td className="py-2 pr-4">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${p.side === 'long' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {p.side?.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 pr-4">{p.quantity?.toFixed(4)}</td>
                <td className="py-2 pr-4">${p.avg_entry_price?.toFixed(2)}</td>
                <td className="py-2 pr-4">${p.notional_value?.toFixed(0)}</td>
                <td className={`py-2 pr-4 font-medium ${pnlClass}`}>
                  {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                </td>
                <td className="py-2 pr-4 text-gray-500">{p.strategy_name || '—'}</td>
                <td className="py-2">
                  <button
                    disabled={closing === p.symbol}
                    onClick={async () => {
                      setClosing(p.symbol);
                      await closePosition(p.symbol, onClose);
                      setClosing(null);
                    }}
                    className="text-xs px-3 py-1 rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                  >
                    {closing === p.symbol ? '...' : 'Close'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
