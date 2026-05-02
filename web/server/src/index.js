const express = require('express');
const http = require('http');
const path = require('path');
const cors = require('cors');
const { WebSocketServer } = require('ws');
const { createWsProxy } = require('./wsProxy');
const { PORT } = require('./config');

const app = express();
app.use(cors());
app.use(express.json());

app.use('/api/status',     require('./routes/status'));
app.use('/api/positions',  require('./routes/positions'));
app.use('/api/strategies', require('./routes/strategies'));
app.use('/api/trades',     require('./routes/trades'));
app.use('/api/equity',     require('./routes/equity'));
app.use('/api/config',     require('./routes/config'));
app.use('/api/control',    require('./routes/control'));
app.use('/api/candles',    require('./routes/candles'));
app.use('/api/backtest',   require('./routes/backtest'));

app.get('/health', (_, res) => res.json({ ok: true }));

// Serve pre-built React app (production / Docker)
const clientDist = path.join(__dirname, '../../client/dist');
app.use(express.static(clientDist));
app.get('*', (req, res) => {
  res.sendFile(path.join(clientDist, 'index.html'));
});

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

wss.on('connection', (ws) => {
  console.log('[ws] Browser client connected');
  ws.on('close', () => console.log('[ws] Browser client disconnected'));
});

createWsProxy(wss);

server.listen(PORT, () => {
  console.log(`Trade web server listening on http://localhost:${PORT}`);
});
