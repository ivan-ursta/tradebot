const WebSocket = require('ws');
const { PYTHON_WS_URL } = require('./config');

function createWsProxy(wss) {
  let upstream = null;
  let reconnectTimer = null;

  function scheduleReconnect() {
    if (reconnectTimer) return; // already scheduled
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, 3000);
  }

  function connect() {
    if (upstream) {
      try { upstream.terminate(); } catch (_) {}
    }
    upstream = new WebSocket(`${PYTHON_WS_URL}/bridge/ws`);

    upstream.on('open', () => {
      console.log('[wsProxy] Connected to Python bridge');
    });

    upstream.on('message', (data) => {
      const msg = data.toString();
      wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
          client.send(msg);
        }
      });
    });

    upstream.on('close', () => {
      console.log('[wsProxy] Python bridge disconnected — retrying in 3s');
      scheduleReconnect();
    });

    upstream.on('error', () => {
      // 'close' always fires after 'error', so let it handle the retry
    });
  }

  connect();
}

module.exports = { createWsProxy };
