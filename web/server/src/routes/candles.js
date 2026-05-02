const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/:symbol', async (req, res) => {
  const symbol = req.params.symbol.toUpperCase();
  const timeframe = req.query.timeframe || '15m';
  const limit = Math.min(parseInt(req.query.limit || '500', 10), 1000);

  try {
    const url = `${PYTHON_BRIDGE_URL}/bridge/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`;
    const r = await fetch(url, { timeout: 15000 });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch (err) {
    res.status(503).json({ error: 'Bridge unreachable', detail: err.message });
  }
});

module.exports = router;