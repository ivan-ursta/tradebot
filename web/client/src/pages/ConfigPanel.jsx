import { useApi } from '../hooks/useApi';

function ConfigTree({ data, depth = 0 }) {
  if (data === null || data === undefined) return <span className="text-gray-400">null</span>;
  if (typeof data !== 'object') {
    return <span className="text-indigo-700 font-mono">{String(data)}</span>;
  }
  if (Array.isArray(data)) {
    return (
      <span className="text-gray-600">
        [{data.map((v, i) => <span key={i}>{i > 0 && ', '}<ConfigTree data={v} depth={depth + 1} /></span>)}]
      </span>
    );
  }
  return (
    <div className={depth > 0 ? 'ml-4 border-l border-gray-200 pl-3' : ''}>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="py-0.5">
          <span className="text-gray-500 text-xs font-mono">{k}: </span>
          {typeof v === 'object' && v !== null ? (
            <details open={depth < 1}>
              <summary className="cursor-pointer text-xs text-gray-400 inline">({Array.isArray(v) ? v.length : Object.keys(v).length} items)</summary>
              <ConfigTree data={v} depth={depth + 1} />
            </details>
          ) : (
            <ConfigTree data={v} depth={depth + 1} />
          )}
        </div>
      ))}
    </div>
  );
}

export function ConfigPanel() {
  const { data, loading, error } = useApi('/api/config');

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-bold text-gray-800">Configuration</h1>
      <div className="bg-white rounded-xl shadow p-5 text-sm">
        {loading && <p className="text-gray-400">Loading...</p>}
        {error && <p className="text-red-500">{error}</p>}
        {data && <ConfigTree data={data.config} />}
      </div>
    </div>
  );
}
