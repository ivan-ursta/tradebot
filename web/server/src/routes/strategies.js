const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/strategies`, { timeout: 3000 });
    res.json(await r.json());
  } catch {
    res.json({ strategies: [], regimes: {} });
  }
});

module.exports = router;
