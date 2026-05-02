import { useState, useEffect } from 'react';
import { useEngineControl } from '../hooks/useEngineControl';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];
const EXCHANGES = ['binance', 'hyperliquid'];
const ORDER_TYPES = ['limit', 'market'];
const ALL_STRATEGIES = ['momentum_breakout', 'mean_reversion', 'funding_filter_momentum', 'market_making'];
const KNOWN_SYMBOLS = ['SOL', 'AVAX', 'BTC', 'ETH', 'OP', 'ARB', 'SUI', 'DOGE'];

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl shadow p-5">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">{title}</h2>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">{label}</label>
      {hint && <p className="text-xs text-gray-400">{hint}</p>}
      {children}
    </div>
  );
}

function NumberInput({ value, onChange, min, max, step = 0.01 }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      min={min}
      max={max}
      step={step}
      className="border border-gray-300 rounded px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  );
}

function Toggle({ value, onChange }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? 'bg-indigo-600' : 'bg-gray-300'}`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${value ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  );
}

function SelectInput({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="border border-gray-300 rounded px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-indigo-400"
    >
      {options.map((o) => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  );
}

function SymbolTag({ symbol, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-1 rounded">
      {symbol}
      <button onClick={() => onRemove(symbol)} className="hover:text-indigo-900 font-bold">×</button>
    </span>
  );
}

export function Settings() {
  const { processRunning, mode, exchange, liveEnabled, loading: ctrlLoading, error: ctrlError, start, stop, refresh } = useEngineControl();

  const [cfg, setCfg] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [confirmLive, setConfirmLive] = useState(false);
  const [symbolInput, setSymbolInput] = useState('');

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((d) => setCfg(d.config))
      .catch(() => setLoadErr('Could not load config'));
  }, []);

  if (loadErr) return <p className="text-red-500">{loadErr}</p>;
  if (!cfg) return <p className="text-gray-400">Loading settings...</p>;

  const set = (path, value) => {
    setCfg((prev) => {
      const next = structuredClone(prev);
      const keys = path.split('.');
      let obj = next;
      for (let i = 0; i < keys.length - 1; i++) obj = obj[keys[i]];
      obj[keys[keys.length - 1]] = value;
      return next;
    });
  };

  const toggleStrategy = (name) => {
    const active = cfg.strategy.active || [];
    const next = active.includes(name) ? active.filter((s) => s !== name) : [...active, name];
    set('strategy.active', next);
  };

  const addSymbol = (sym) => {
    const s = sym.toUpperCase().trim();
    if (!s) return;
    const wl = cfg.markets.whitelist || [];
    if (!wl.includes(s)) set('markets.whitelist', [...wl, s]);
    setSymbolInput('');
  };

  const removeSymbol = (sym) => {
    set('markets.whitelist', (cfg.markets.whitelist || []).filter((s) => s !== sym));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error);
      setSaveMsg({ type: 'ok', text: 'Saved. Restart the engine to apply changes.' });
    } catch (e) {
      setSaveMsg({ type: 'err', text: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleModeSwitch = async (target) => {
    if (target === 'live') {
      if (!liveEnabled) {
        setSaveMsg({ type: 'err', text: 'Live trading not enabled. Set LIVE_TRADING_ENABLED=true in .env first.' });
        return;
      }
      setConfirmLive(true);
      return;
    }
    if (processRunning) await stop();
    await start(target);
  };

  const confirmSwitchToLive = async () => {
    setConfirmLive(false);
    if (processRunning) await stop();
    await start('live');
  };

  const handleExchangeSwitch = async (target) => {
    if (target === exchange) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trading: { exchange: target } }),
      });
      if (!res.ok) throw new Error((await res.json()).error || 'Save failed');
      // also update local cfg state
      setCfg((prev) => prev ? { ...prev, trading: { ...prev.trading, exchange: target } } : prev);
      if (processRunning) {
        await stop();
        await start(mode);
      }
      await refresh();
      setSaveMsg({ type: 'ok', text: `Switched to ${target}.${processRunning ? ' Engine restarted.' : ' Start the engine to apply.'}` });
    } catch (e) {
      setSaveMsg({ type: 'err', text: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Config'}
        </button>
      </div>

      {saveMsg && (
        <div className={`text-sm px-4 py-2 rounded-lg ${saveMsg.type === 'ok' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
          {saveMsg.text}
        </div>
      )}

      {/* Live confirmation modal */}
      {confirmLive && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
            <div className="text-lg font-bold text-red-600 mb-2">Switch to Live Trading?</div>
            <p className="text-sm text-gray-600 mb-4">
              This will restart the engine in <strong>LIVE mode</strong> — real orders will be placed on the exchange with real funds.
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setConfirmLive(false)} className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Cancel</button>
              <button onClick={confirmSwitchToLive} className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700 font-semibold">Yes, go LIVE</button>
            </div>
          </div>
        </div>
      )}

      {/* Engine Control */}
      <Section title="Engine Control">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Status:</span>
            <span className={`text-sm font-semibold ${processRunning ? 'text-green-600' : 'text-gray-400'}`}>
              {processRunning ? 'Running' : 'Stopped'}
            </span>
          </div>
          {processRunning ? (
            <button onClick={stop} disabled={ctrlLoading} className="px-3 py-1.5 text-sm rounded-lg bg-red-100 text-red-700 hover:bg-red-200 font-medium disabled:opacity-50">
              Stop Engine
            </button>
          ) : (
            <button onClick={() => start(mode)} disabled={ctrlLoading} className="px-3 py-1.5 text-sm rounded-lg bg-green-100 text-green-700 hover:bg-green-200 font-medium disabled:opacity-50">
              Start Engine
            </button>
          )}
          {ctrlError && <span className="text-xs text-red-500">{ctrlError}</span>}
        </div>

        <Field label="Trading Mode" hint="Live mode requires LIVE_TRADING_ENABLED=true in .env and restarts the engine.">
          <div className="flex gap-2">
            {['paper', 'live'].map((m) => (
              <button
                key={m}
                onClick={() => handleModeSwitch(m)}
                disabled={ctrlLoading}
                className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors disabled:opacity-50 ${
                  mode === m
                    ? m === 'live'
                      ? 'bg-red-600 text-white border-red-600'
                      : 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}
              >
                {m === 'live' ? 'Live' : 'Paper'}
                {m === 'live' && !liveEnabled && <span className="ml-1 text-xs opacity-70">(locked)</span>}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Exchange" hint="Saves config and restarts the engine automatically.">
          <div className="flex gap-2">
            {[
              { id: 'binance', label: 'Binance', sub: 'USDT-M Futures' },
              { id: 'hyperliquid', label: 'Hyperliquid', sub: 'Perps' },
            ].map(({ id, label, sub }) => (
              <button
                key={id}
                onClick={() => handleExchangeSwitch(id)}
                disabled={saving || ctrlLoading}
                className={`px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors disabled:opacity-50 flex flex-col items-start ${
                  exchange === id
                    ? 'bg-yellow-500 text-white border-yellow-500'
                    : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}
              >
                <span>{label}</span>
                <span className={`text-xs font-normal ${exchange === id ? 'text-yellow-100' : 'text-gray-400'}`}>{sub}</span>
              </button>
            ))}
          </div>
        </Field>
      </Section>

      {/* Trading */}
      <Section title="Trading">
        <Field label="Dry Run" hint="When on, no real orders are placed even in live mode.">
          <Toggle value={cfg.trading.dry_run} onChange={(v) => set('trading.dry_run', v)} />
        </Field>
        <Field label="Timeframe">
          <SelectInput value={cfg.strategy.timeframe} onChange={(v) => set('strategy.timeframe', v)} options={TIMEFRAMES} />
        </Field>
        <Field label="Multi-strategy" hint="Allow multiple concurrent strategies sharing the risk budget.">
          <Toggle value={cfg.strategy.multi_strategy} onChange={(v) => set('strategy.multi_strategy', v)} />
        </Field>
      </Section>

      {/* Markets */}
      <Section title="Markets">
        <Field label="Symbol Whitelist" hint="Research validated: SOL and AVAX only. Others are experimental.">
          <div className="flex flex-wrap gap-2 mb-2">
            {(cfg.markets.whitelist || []).map((s) => (
              <SymbolTag key={s} symbol={s} onRemove={removeSymbol} />
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && addSymbol(symbolInput)}
              placeholder="Add symbol…"
              className="border border-gray-300 rounded px-3 py-1.5 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <div className="flex flex-wrap gap-1">
              {KNOWN_SYMBOLS.filter((s) => !(cfg.markets.whitelist || []).includes(s)).map((s) => (
                <button key={s} onClick={() => addSymbol(s)} className="text-xs px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-600">{s}</button>
              ))}
            </div>
          </div>
        </Field>
        <Field label="Min Volume (USD)">
          <NumberInput value={cfg.markets.min_volume_usd} onChange={(v) => set('markets.min_volume_usd', v)} min={0} step={100000} />
        </Field>
        <Field label="Max Spread Fraction" hint="Maximum allowed bid-ask spread as fraction of mid price.">
          <NumberInput value={cfg.markets.max_spread_fraction} onChange={(v) => set('markets.max_spread_fraction', v)} min={0} max={0.1} step={0.0005} />
        </Field>
      </Section>

      {/* Risk */}
      <Section title="Risk Management">
        <Field label="Max Risk per Trade" hint="Fraction of equity risked per trade.">
          <div className="flex items-center gap-3">
            <NumberInput value={cfg.risk.max_risk_per_trade} onChange={(v) => set('risk.max_risk_per_trade', v)} min={0.001} max={0.1} step={0.001} />
            <span className="text-sm text-gray-500">{(cfg.risk.max_risk_per_trade * 100).toFixed(1)}%</span>
          </div>
        </Field>
        <Field label="Max Total Exposure">
          <div className="flex items-center gap-3">
            <NumberInput value={cfg.risk.max_total_exposure} onChange={(v) => set('risk.max_total_exposure', v)} min={0.05} max={1} step={0.05} />
            <span className="text-sm text-gray-500">{(cfg.risk.max_total_exposure * 100).toFixed(0)}%</span>
          </div>
        </Field>
        <Field label="Max Single Market Exposure">
          <div className="flex items-center gap-3">
            <NumberInput value={cfg.risk.max_single_market_exposure} onChange={(v) => set('risk.max_single_market_exposure', v)} min={0.01} max={0.5} step={0.01} />
            <span className="text-sm text-gray-500">{(cfg.risk.max_single_market_exposure * 100).toFixed(0)}%</span>
          </div>
        </Field>
        <Field label="Max Open Positions">
          <NumberInput value={cfg.risk.max_open_positions} onChange={(v) => set('risk.max_open_positions', Math.round(v))} min={1} max={20} step={1} />
        </Field>
        <Field label="Max Daily Loss" hint="Kill-switch triggers when daily loss exceeds this.">
          <div className="flex items-center gap-3">
            <NumberInput value={cfg.risk.max_daily_loss} onChange={(v) => set('risk.max_daily_loss', v)} min={0.01} max={0.5} step={0.01} />
            <span className="text-sm text-gray-500">{(cfg.risk.max_daily_loss * 100).toFixed(0)}%</span>
          </div>
        </Field>
        <Field label="Kill-Switch Drawdown" hint="Kill-switch triggers when drawdown from peak exceeds this.">
          <div className="flex items-center gap-3">
            <NumberInput value={cfg.risk.kill_switch_drawdown} onChange={(v) => set('risk.kill_switch_drawdown', v)} min={0.01} max={0.9} step={0.01} />
            <span className="text-sm text-gray-500">{(cfg.risk.kill_switch_drawdown * 100).toFixed(0)}%</span>
          </div>
        </Field>
        <Field label="Stop Loss ATR Multiplier">
          <NumberInput value={cfg.risk.stop_loss_atr_mult} onChange={(v) => set('risk.stop_loss_atr_mult', v)} min={0.5} max={10} step={0.5} />
        </Field>
        <Field label="Take Profit ATR Multiplier">
          <NumberInput value={cfg.risk.take_profit_atr_mult} onChange={(v) => set('risk.take_profit_atr_mult', v)} min={0.5} max={20} step={0.5} />
        </Field>
        <Field label="Max Leverage">
          <NumberInput value={cfg.risk.max_leverage} onChange={(v) => set('risk.max_leverage', Math.round(v))} min={1} max={20} step={1} />
        </Field>
      </Section>

      {/* Strategies */}
      <Section title="Active Strategies">
        <p className="text-xs text-gray-400 -mt-1">Research validated: momentum_breakout on SOL/AVAX. Others are experimental.</p>
        {ALL_STRATEGIES.map((name) => (
          <div key={name} className="flex items-center justify-between">
            <span className="text-sm text-gray-700 font-mono">{name}</span>
            <Toggle
              value={(cfg.strategy.active || []).includes(name)}
              onChange={() => toggleStrategy(name)}
            />
          </div>
        ))}
      </Section>

      {/* Execution */}
      <Section title="Execution">
        <Field label="Order Type">
          <SelectInput value={cfg.execution.order_type} onChange={(v) => set('execution.order_type', v)} options={ORDER_TYPES} />
        </Field>
        <Field label="Limit Slippage (bps)">
          <NumberInput value={cfg.execution.limit_slippage_bps} onChange={(v) => set('execution.limit_slippage_bps', Math.round(v))} min={0} max={100} step={1} />
        </Field>
      </Section>

      {/* Paper */}
      <Section title="Paper Trading">
        <Field label="Starting Balance (USD)">
          <NumberInput value={cfg.paper.starting_balance} onChange={(v) => set('paper.starting_balance', v)} min={100} max={10000000} step={1000} />
        </Field>
        <Field label="Fee Rate (fraction)" hint="4 bps = 0.0004">
          <NumberInput value={cfg.paper.fee_rate} onChange={(v) => set('paper.fee_rate', v)} min={0} max={0.01} step={0.0001} />
        </Field>
        <Field label="Slippage (bps)">
          <NumberInput value={cfg.paper.slippage_bps} onChange={(v) => set('paper.slippage_bps', Math.round(v))} min={0} max={50} step={1} />
        </Field>
      </Section>

      <div className="flex justify-end pb-6">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Config'}
        </button>
      </div>
    </div>
  );
}