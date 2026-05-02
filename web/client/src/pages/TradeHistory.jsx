import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { TradesTable } from '../components/tables/TradesTable';

export function TradeHistory() {
  const [page, setPage] = useState(1);
  const [symbol, setSymbol] = useState('');
  const [strategy, setStrategy] = useState('');
  const limit = 50;

  const params = new URLSearchParams({ page, limit });
  if (symbol) params.set('symbol', symbol);
  if (strategy) params.set('strategy', strategy);

  const { data, loading } = useApi(`/api/trades?${params}`, 0);

  const totalPages = data ? Math.ceil(data.total / limit) : 1;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold text-gray-800">Trade History</h1>

      <div className="flex gap-3 flex-wrap">
        <input
          className="border rounded px-3 py-1.5 text-sm w-32"
          placeholder="Symbol"
          value={symbol}
          onChange={(e) => { setSymbol(e.target.value.toUpperCase()); setPage(1); }}
        />
        <input
          className="border rounded px-3 py-1.5 text-sm w-44"
          placeholder="Strategy"
          value={strategy}
          onChange={(e) => { setStrategy(e.target.value); setPage(1); }}
        />
        {(symbol || strategy) && (
          <button
            className="text-xs px-3 py-1.5 rounded bg-gray-200 text-gray-700 hover:bg-gray-300"
            onClick={() => { setSymbol(''); setStrategy(''); setPage(1); }}
          >
            Clear
          </button>
        )}
        {data && <span className="text-sm text-gray-400 self-center">{data.total} trade(s)</span>}
      </div>

      <div className="bg-white rounded-xl shadow p-5">
        {loading ? (
          <p className="text-gray-400 text-sm">Loading...</p>
        ) : (
          <TradesTable trades={data?.trades || []} />
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex gap-2 items-center text-sm">
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300 disabled:opacity-40"
          >
            Prev
          </button>
          <span className="text-gray-600">{page} / {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
