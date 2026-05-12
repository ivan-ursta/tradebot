const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  const { limit = 200, symbol } = req.query;
  const params = new URLSearchParams({ limit });
  if (symbol) params.set('symbol', symbol);
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/signals?${params}`, { timeout: 5000 });
    res.json(await r.json());
  } catch {
    res.json({ signals: [] });
  }
});

module.exports = router;