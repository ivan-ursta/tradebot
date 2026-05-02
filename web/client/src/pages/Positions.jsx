import { useApi } from '../hooks/useApi';
import { PositionsTable } from '../components/tables/PositionsTable';

export function Positions() {
  const { data, loading, refetch } = useApi('/api/positions', 5000);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Open Positions</h1>
        <span className="text-sm text-gray-400">{data?.count ?? 0} position(s)</span>
      </div>
      <div className="bg-white rounded-xl shadow p-5">
        {loading ? (
          <p className="text-gray-400 text-sm">Loading...</p>
        ) : (
          <PositionsTable positions={data?.positions || []} onClose={refetch} />
        )}
      </div>
    </div>
  );
}
