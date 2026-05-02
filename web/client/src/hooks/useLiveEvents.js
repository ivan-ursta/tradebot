import { useEffect, useState } from 'react';
import { useWebSocket } from './useWebSocket';

export function useLiveEvents() {
  const message = useWebSocket('/ws');
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]);

  useEffect(() => {
    if (!message) return;
    if (message.type === 'state_snapshot') {
      setSnapshot(message.data);
    } else if (message.type === 'event') {
      setEvents((prev) => [...prev.slice(-99), { ...message.data, _id: Date.now() + Math.random() }]);
    }
  }, [message]);

  return { snapshot, events };
}
