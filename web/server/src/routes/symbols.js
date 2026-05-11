const express = require('express');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/symbols`);
    res.json(await r.json());
  } catch {
    res.json({ symbols: [], count: 0 });
  }
});

router.post('/add', async (req, res) => {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/symbols/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: req.body.symbol }),
    });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch (err) {
    res.status(503).json({ error: 'Bridge unreachable', detail: err.message });
  }
});

router.post('/remove', async (req, res) => {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/symbols/remove`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: req.body.symbol }),
    });
    const data = await r.json();
    res.status(r.status).json(data);
  } catch (err) {
    res.status(503).json({ error: 'Bridge unreachable', detail: err.message });
  }
});

module.exports = router;
