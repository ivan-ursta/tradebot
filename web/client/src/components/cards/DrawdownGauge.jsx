export function DrawdownGauge({ drawdown }) {
  const pct = (drawdown ?? 0) * 100;
  const color = pct < 5 ? 'bg-green-500' : pct < 10 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="bg-white rounded-xl shadow p-5 flex flex-col gap-2">
      <div className="text-xs text-gray-500 uppercase tracking-wide">Drawdown</div>
      <div className="text-2xl font-bold text-gray-900">{pct.toFixed(2)}%</div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="text-xs text-gray-400">
        {pct < 5 ? 'Healthy' : pct < 10 ? 'Caution' : 'High risk'}
      </div>
    </div>
  );
}
