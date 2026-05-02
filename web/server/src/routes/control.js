const express = require('express');
const fs = require('fs');
const yaml = require('js-yaml');
const { PYTHON_BRIDGE_URL, CONFIG_YAML_PATH } = require('../config');

const router = express.Router();

let currentMode = 'paper';

function isLiveEnabled() {
  return (
    process.env.LIVE_TRADING_ENABLED === 'true' ||
    process.env.BINANCE_LIVE_TRADING_ENABLED === 'true'
  );
}

function readExchange() {
  try {
    const cfg = yaml.load(fs.readFileSync(CONFIG_YAML_PATH, 'utf8'));
    return cfg?.trading?.exchange || 'binance';
  } catch {
    return 'binance';
  }
}

async function bridgeStatus() {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/status`, {
      signal: AbortSignal.timeout(3000),
    });
    return await r.json();
  } catch {
    return null;
  }
}

router.get('/mode', async (req, res) => {
  const bs = await bridgeStatus();
  if (bs?.mode) currentMode = bs.mode;
  res.json({ mode: currentMode, live_enabled: isLiveEnabled(), exchange: readExchange() });
});

// In Docker the engine runs as the Python container's own process.
// /start just verifies the bridge is reachable; the engine is always running.
router.post('/start', async (req, res) => {
  const mode = req.body?.mode || 'paper';
  if (!['paper', 'live'].includes(mode)) {
    return res.status(400).json({ error: 'Invalid mode. Use "paper" or "live".' });
  }
  if (mode === 'live' && !isLiveEnabled()) {
    return res.status(403).json({
      error: 'Live trading not enabled',
      detail: 'Set LIVE_TRADING_ENABLED=true in .env',
    });
  }

  const bs = await bridgeStatus();
  if (!bs) {
    return res.status(503).json({ error: 'Python engine is not reachable' });
  }

  currentMode = mode;
  res.json({ started: true, mode });
});

router.post('/stop', async (req, res) => {
  // Cannot stop the Docker container process from here; just report status
  res.json({ stopped: false, detail: 'Engine managed by Docker — stop via docker compose down' });
});

router.get('/status', async (req, res) => {
  const bs = await bridgeStatus();
  if (bs?.mode) currentMode = bs.mode;
  res.json({
    running: bs !== null,
    pid: null,
  });
});

router.post('/close/:symbol', async (req, res) => {
  const symbol = req.params.symbol.toUpperCase();
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/close/${symbol}`, {
      method: 'POST',
      signal: AbortSignal.timeout(5000),
    });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch {
    res.status(503).json({ error: 'Python bridge unreachable' });
  }
});

module.exports = router;
