require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

module.exports = {
  PORT: parseInt(process.env.PORT || '3001'),
  PYTHON_BRIDGE_URL: process.env.PYTHON_BRIDGE_URL || 'http://127.0.0.1:8765',
  PYTHON_WS_URL: process.env.PYTHON_WS_URL || 'ws://127.0.0.1:8765',
  DB_PATH: process.env.DB_PATH || '/home/dell/trade/data/trading.db',
  CONFIG_YAML_PATH: process.env.CONFIG_YAML_PATH || '/home/dell/trade/config/config.yaml',
  TRADE_ROOT: process.env.TRADE_ROOT || '/home/dell/trade',
};
