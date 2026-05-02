const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  const { page = 1, limit = 50, symbol, strategy } = req.query;
  const params = new URLSearchParams({ page, limit });
  if (symbol) params.set('symbol', symbol);
  if (strategy) params.set('strategy', strategy);
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/trades?${params}`, { timeout: 5000 });
    res.json(await r.json());
  } catch {
    res.json({ trades: [], total: 0, page: parseInt(page), limit: parseInt(limit) });
  }
});

module.exports = router;
