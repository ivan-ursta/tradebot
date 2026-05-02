export function EquityCard({ equity, startingEquity, dailyPnlPct }) {
  const pct = dailyPnlPct ?? 0;
  const positive = pct >= 0;
  return (
    <div className="bg-white rounded-xl shadow p-5 flex flex-col gap-1">
      <div className="text-xs text-gray-500 uppercase tracking-wide">Equity</div>
      <div className="text-2xl font-bold text-gray-900">
        {equity != null ? `$${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
      </div>
      <div className={`text-sm font-medium ${positive ? 'text-green-600' : 'text-red-600'}`}>
        {positive ? '+' : ''}{(pct * 100).toFixed(2)}% today
      </div>
      {startingEquity != null && (
        <div className="text-xs text-gray-400">Start: ${startingEquity.toLocaleString()}</div>
      )}
    </div>
  );
}
