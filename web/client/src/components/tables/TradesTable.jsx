export function TradesTable({ trades }) {
  if (!trades || trades.length === 0) {
    return <p className="text-gray-400 text-sm py-4">No trades yet</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b text-xs uppercase">
            <th className="py-2 pr-4">Symbol</th>
            <th className="py-2 pr-4">Strategy</th>
            <th className="py-2 pr-4">Side</th>
            <th className="py-2 pr-4">Qty</th>
            <th className="py-2 pr-4">Entry</th>
            <th className="py-2 pr-4">Exit</th>
            <th className="py-2 pr-4">Net PnL</th>
            <th className="py-2 pr-4">Fees</th>
            <th className="py-2">Closed</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnl = t.net_pnl ?? 0;
            const pnlClass = pnl >= 0 ? 'text-green-600' : 'text-red-600';
            return (
              <tr key={t.id ?? i} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4 font-semibold">{t.symbol}</td>
                <td className="py-2 pr-4 text-gray-500">{t.strategy || '—'}</td>
                <td className="py-2 pr-4">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${t.side === 'long' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {t.side?.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 pr-4">{t.quantity?.toFixed(4)}</td>
                <td className="py-2 pr-4">${t.entry_price?.toFixed(2)}</td>
                <td className="py-2 pr-4">${t.exit_price?.toFixed(2)}</td>
                <td className={`py-2 pr-4 font-medium ${pnlClass}`}>
                  {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                </td>
                <td className="py-2 pr-4 text-gray-500">${t.fees?.toFixed(3)}</td>
                <td className="py-2 text-gray-500 text-xs">
                  {t.exit_time ? new Date(t.exit_time).toLocaleString() : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
