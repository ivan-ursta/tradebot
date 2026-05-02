const WebSocket = require('ws');
const { PYTHON_WS_URL } = require('./config');

function createWsProxy(wss) {
  let upstream = null;
  let reconnectTimer = null;

  function connect() {
    if (upstream) {
      try { upstream.terminate(); } catch (_) {}
    }
    upstream = new WebSocket(`${PYTHON_WS_URL}/bridge/ws`);

    upstream.on('open', () => {
      console.log('[wsProxy] Connected to Python bridge');
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
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
      reconnectTimer = setTimeout(connect, 3000);
    });

    upstream.on('error', () => {
      reconnectTimer = setTimeout(connect, 3000);
    });
  }

  connect();
}

module.exports = { createWsProxy };
