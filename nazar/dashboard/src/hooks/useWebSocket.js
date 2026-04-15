/**
 * Nazar — WebSocket Hook
 *
 * Provides real-time event streaming from the server.
 * Automatically authenticates, reconnects on disconnect, and
 * allows subscribing to specific event types.
 *
 * Usage:
 *   const { subscribe, isConnected, lastEvent } = useWebSocket();
 *
 *   useEffect(() => {
 *     const unsub = subscribe('new_message', (data) => {
 *       setMessages(prev => [...prev, data]);
 *     });
 *     return unsub; // cleanup on unmount
 *   }, [subscribe]);
 */

import { useEffect, useRef, useCallback, useState } from 'react';

const RECONNECT_DELAY_MS = 3000;
const PING_INTERVAL_MS = 30_000;

export function useWebSocket() {
  const wsRef = useRef(null);
  const listenersRef = useRef(new Map()); // eventType → Set<handler>
  const pingRef = useRef(null);
  const reconnectRef = useRef(null);
  const mountedRef = useRef(true);

  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const token = localStorage.getItem('nazar_token');
    const apiKey = localStorage.getItem('nazar_api_key');

    if (!token && !apiKey) return; // Not authenticated yet

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const authParam = token ? `token=${token}` : `key=${apiKey}`;
    const url = `${protocol}//${window.location.host}/ws?${authParam}`;

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setIsConnected(true);
      console.debug('[WS] Connected');

      // Start ping interval
      if (pingRef.current) clearInterval(pingRef.current);
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.type === 'ping' || parsed.type === 'pong') return;
        if (parsed.type === 'connected') return;

        setLastEvent(parsed);

        // Notify all type-specific listeners
        const handlers = listenersRef.current.get(parsed.type);
        if (handlers) {
          handlers.forEach((fn) => {
            try { fn(parsed.data ?? parsed); }
            catch (e) { console.error('[WS] Handler error:', e); }
          });
        }

        // Also notify wildcard listeners
        const wildcards = listenersRef.current.get('*');
        if (wildcards) {
          wildcards.forEach((fn) => {
            try { fn(parsed); }
            catch (e) { console.error('[WS] Wildcard handler error:', e); }
          });
        }
      } catch {
        // Ignore non-JSON messages
      }
    };

    ws.onerror = (err) => {
      console.debug('[WS] Error:', err);
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      console.debug('[WS] Disconnected — reconnecting in', RECONNECT_DELAY_MS, 'ms');
      if (pingRef.current) clearInterval(pingRef.current);
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (pingRef.current) clearInterval(pingRef.current);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  /**
   * Subscribe to an event type.
   *
   * @param {string}   eventType - e.g. "new_message", "draft_ready", "*" for all
   * @param {Function} handler   - Called with event data when event arrives
   * @returns {Function}         - Unsubscribe function
   */
  const subscribe = useCallback((eventType, handler) => {
    if (!listenersRef.current.has(eventType)) {
      listenersRef.current.set(eventType, new Set());
    }
    listenersRef.current.get(eventType).add(handler);

    return () => {
      const handlers = listenersRef.current.get(eventType);
      if (handlers) handlers.delete(handler);
    };
  }, []);

  /**
   * Send a raw message to the server (for custom use cases).
   */
  const send = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        typeof message === 'string' ? message : JSON.stringify(message)
      );
    }
  }, []);

  return { subscribe, send, isConnected, lastEvent };
}
