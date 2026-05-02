const express = require('express');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

// POST /api/backtest/run  — proxy to Python bridge
router.post('/run', async (req, res) => {
  const symbol = (req.body.symbol || 'SOL').toUpperCase();
  try {
    const response = await fetch(`${PYTHON_BRIDGE_URL}/bridge/backtest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    });
    const data = await response.json();
    // Python returns job_id; remap to jobId for frontend compatibility
    res.json({ jobId: data.job_id, symbol: data.symbol });
  } catch (err) {
    res.status(502).json({ error: `Bridge unreachable: ${err.message}` });
  }
});

// GET /api/backtest/status/:jobId  — proxy to Python bridge
router.get('/status/:jobId', async (req, res) => {
  const since = req.query.since || '0';
  try {
    const response = await fetch(
      `${PYTHON_BRIDGE_URL}/bridge/backtest/status/${req.params.jobId}?since=${since}`
    );
    if (response.status === 404) return res.status(404).json({ error: 'Job not found' });
    const data = await response.json();
    // Python returns exit_code; remap to exitCode for frontend compatibility
    res.json({
      symbol: data.symbol,
      running: data.running,
      exitCode: data.exit_code,
      logs: data.logs,
      total: data.total,
    });
  } catch (err) {
    res.status(502).json({ error: `Bridge unreachable: ${err.message}` });
  }
});

// GET /api/backtest/results/:symbol  — proxy to Python bridge (it owns the export files)
router.get('/results/:symbol', async (req, res) => {
  const symbol = req.params.symbol.toUpperCase();
  try {
    const response = await fetch(`${PYTHON_BRIDGE_URL}/bridge/backtest/results/${symbol}`);
    if (response.status === 404) return res.status(404).json({ error: 'No results found. Run a backtest first.' });
    const data = await response.json();
    res.json(data);
  } catch (err) {
    res.status(502).json({ error: `Bridge unreachable: ${err.message}` });
  }
});

// GET /api/backtest/list  — proxy to Python bridge
router.get('/list', async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_BRIDGE_URL}/bridge/backtest/list`);
    const data = await response.json();
    res.json(data);
  } catch {
    res.json({ symbols: [] });
  }
});

module.exports = router;
