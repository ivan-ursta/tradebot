import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';

export function EquityChart({ points }) {
  if (!points || points.length === 0) {
    return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">No data yet</div>;
  }

  const formatted = points.map((p) => ({
    ...p,
    time: new Date(p.timestamp).toLocaleDateString(),
    equity: parseFloat(p.equity?.toFixed(2)),
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={formatted} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="time" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
        <Tooltip formatter={(v) => `$${v.toLocaleString()}`} />
        <Line type="monotone" dataKey="equity" stroke="#6366f1" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
