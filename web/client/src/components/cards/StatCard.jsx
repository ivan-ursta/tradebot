export function StatCard({ label, value, sub, valueClass = '' }) {
  return (
    <div className="bg-white rounded-xl shadow p-5 flex flex-col gap-1">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold text-gray-900 ${valueClass}`}>{value ?? '—'}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}
