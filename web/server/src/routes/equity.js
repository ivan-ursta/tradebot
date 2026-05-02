const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  const days = req.query.days || '30';
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/equity?days=${days}`, { timeout: 5000 });
    res.json(await r.json());
  } catch {
    res.json({ points: [] });
  }
});

module.exports = router;
