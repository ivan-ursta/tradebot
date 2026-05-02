import { useEffect, useRef, useState } from 'react';

export function useWebSocket(url) {
  const [lastMessage, setLastMessage] = useState(null);
  const ws = useRef(null);

  useEffect(() => {
    function connect() {
      const loc = window.location;
      const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
      const fullUrl = url.startsWith('ws') ? url : `${proto}//${loc.host}${url}`;
      ws.current = new WebSocket(fullUrl);
      ws.current.onmessage = (e) => {
        try { setLastMessage(JSON.parse(e.data)); } catch (_) {}
      };
      ws.current.onclose = () => setTimeout(connect, 3000);
      ws.current.onerror = () => {};
    }
    connect();
    return () => { if (ws.current) ws.current.close(); };
  }, [url]);

  return lastMessage;
}
