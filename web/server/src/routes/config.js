const express = require('express');
const fs = require('fs');
const yaml = require('js-yaml');
const { CONFIG_YAML_PATH } = require('../config');

const router = express.Router();

function deepMerge(target, source) {
  const out = { ...target };
  for (const key of Object.keys(source)) {
    if (
      source[key] !== null &&
      typeof source[key] === 'object' &&
      !Array.isArray(source[key]) &&
      typeof target[key] === 'object' &&
      target[key] !== null &&
      !Array.isArray(target[key])
    ) {
      out[key] = deepMerge(target[key], source[key]);
    } else {
      out[key] = source[key];
    }
  }
  return out;
}

router.get('/', (req, res) => {
  try {
    const raw = fs.readFileSync(CONFIG_YAML_PATH, 'utf8');
    const parsed = yaml.load(raw);
    res.json({ config: parsed });
  } catch (err) {
    res.status(500).json({ error: 'Could not read config', detail: err.message });
  }
});

router.put('/', (req, res) => {
  try {
    const updates = req.body;
    if (!updates || typeof updates !== 'object') {
      return res.status(400).json({ error: 'Request body must be a JSON object' });
    }
    const raw = fs.readFileSync(CONFIG_YAML_PATH, 'utf8');
    const current = yaml.load(raw);
    const merged = deepMerge(current, updates);
    fs.writeFileSync(CONFIG_YAML_PATH, yaml.dump(merged, { lineWidth: -1, quotingType: '"' }));
    res.json({ saved: true });
  } catch (err) {
    res.status(500).json({ error: 'Could not save config', detail: err.message });
  }
});

module.exports = router;
