const express = require('express');
const fetch = require('node-fetch');
const { PYTHON_BRIDGE_URL } = require('../config');

const router = express.Router();

router.get('/', async (req, res) => {
  try {
    const r = await fetch(`${PYTHON_BRIDGE_URL}/bridge/status`, { timeout: 3000 });
    const data = await r.json();
    res.json({ ...data, running: true });
  } catch {
    res.json({ running: false, kill_switch_active: false, equity: null });
  }
});

module.exports = router;
