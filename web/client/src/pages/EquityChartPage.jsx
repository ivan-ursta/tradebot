import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { EquityChart } from '../components/charts/EquityChart';

const DAY_OPTIONS = [7, 30, 90, 365];

export function EquityChartPage() {
  const [days, setDays] = useState(30);
  const { data, loading } = useApi(`/api/equity?days=${days}`);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Equity Curve</h1>
        <div className="flex gap-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`text-xs px-3 py-1 rounded ${days === d ? 'bg-indigo-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-xl shadow p-5">
        {loading ? <p className="text-gray-400 text-sm">Loading...</p> : <EquityChart points={data?.points || []} />}
      </div>
    </div>
  );
}
