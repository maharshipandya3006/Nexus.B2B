import { useEffect, useRef, useState, useCallback } from 'react';

export function getToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('token');
  }
  return null;
}

export interface RealtimeEvent {
  event_id: string;
  event_type: string;
  transaction_id?: number;
  user_id?: number;
  timestamp: string;
  data: Record<string, any>;
}

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

interface UseRealtimeOptions {
  onEvent: (event: RealtimeEvent) => void;
  onReconnect?: () => void;
}

function getWebSocketBaseUrl(): string {
  // If NEXT_PUBLIC_API_URL is configured, derive ws URL from it
  let apiUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim();
  // Strip trailing /api or trailing slashes so base is clean protocol + host
  apiUrl = apiUrl.replace(/\/api\/?$/, '').replace(/\/+$/, '');

  if (apiUrl.startsWith('https://')) {
    return apiUrl.replace('https://', 'wss://');
  } else if (apiUrl.startsWith('http://')) {
    return apiUrl.replace('http://', 'ws://');
  }
  // Fallback to current browser window host
  if (typeof window !== 'undefined' && window.location?.host) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}`;
  }
  return 'ws://localhost:8000';
}


/**
 * Hook for subscribing to a transaction-specific real-time channel.
 */
export function useTransactionRealtime(
  transactionId: number | null | undefined,
  { onEvent, onReconnect }: UseRealtimeOptions
) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const seenEventIdsRef = useRef<Set<string>>(new Set());
  const hasConnectedOnceRef = useRef<boolean>(false);

  // Stable callback refs
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onReconnectRef = useRef(onReconnect);
  onReconnectRef.current = onReconnect;

  const connect = useCallback(() => {
    if (!transactionId || typeof window === 'undefined') return;

    const token = getToken();
    if (!token) {
      setStatus('disconnected');
      return;
    }

    // Clean up any existing connection
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }

    const wsBase = getWebSocketBaseUrl();
    const wsUrl = `${wsBase}/api/ws/transactions/${transactionId}?token=${encodeURIComponent(token)}`;

    setStatus(hasConnectedOnceRef.current ? 'reconnecting' : 'connecting');

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus('connected');
        reconnectAttemptRef.current = 0;

        // If this is a reconnection, trigger database catch-up sync
        if (hasConnectedOnceRef.current && onReconnectRef.current) {
          onReconnectRef.current();
        }
        hasConnectedOnceRef.current = true;

        // Start aggressive 10s heartbeat ping to keep Render / Edge proxies permanently warm
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }));
          }
        }, 10000);
      };

      ws.onmessage = (event) => {
        try {
          const payload: RealtimeEvent = JSON.parse(event.data);

          // Deduplicate events by event_id
          if (payload.event_id) {
            if (seenEventIdsRef.current.has(payload.event_id)) {
              return;
            }
            seenEventIdsRef.current.add(payload.event_id);
            // Prune memory if set grows large
            if (seenEventIdsRef.current.size > 200) {
              const items = Array.from(seenEventIdsRef.current);
              seenEventIdsRef.current = new Set(items.slice(-100));
            }
          }

          if (payload.event_type !== 'HEARTBEAT') {
            onEventRef.current(payload);
          }
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = () => {
        // Handled in onclose
      };

      ws.onclose = (event) => {
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

        // Do not reconnect if unauthorized or deliberately closed
        if (event.code === 4401 || event.code === 4403 || event.code === 4404) {
          console.warn(`WebSocket closed with non-recoverable code: ${event.code}`);
          setStatus('disconnected');
          return;
        }

        // Skip the 'disconnected' flash — go straight to 'reconnecting'
        // so the UI indicator doesn't flicker between states
        setStatus('reconnecting');

        // Exponential backoff reconnect: 1s, 2s, 4s, up to 10s
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
        reconnectAttemptRef.current += 1;

        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      };
    } catch (err) {
      console.error('Failed to initialize WebSocket:', err);
      setStatus('disconnected');
    }
  }, [transactionId]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) {
        try {
          wsRef.current.close(1000, 'Component unmounted');
        } catch {}
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { status };
}

/**
 * Hook for subscribing to live dashboard feeds (buyer or merchant overview).
 */
export function useDashboardRealtime({ onEvent, onReconnect }: UseRealtimeOptions) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const seenEventIdsRef = useRef<Set<string>>(new Set());
  const hasConnectedOnceRef = useRef<boolean>(false);

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onReconnectRef = useRef(onReconnect);
  onReconnectRef.current = onReconnect;

  const connect = useCallback(() => {
    if (typeof window === 'undefined') return;

    const token = getToken();
    if (!token) {
      setStatus('disconnected');
      return;
    }

    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {}
      wsRef.current = null;
    }

    const wsBase = getWebSocketBaseUrl();
    const wsUrl = `${wsBase}/api/ws/dashboard?token=${encodeURIComponent(token)}`;

    setStatus(hasConnectedOnceRef.current ? 'reconnecting' : 'connecting');

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus('connected');
        reconnectAttemptRef.current = 0;

        if (hasConnectedOnceRef.current && onReconnectRef.current) {
          onReconnectRef.current();
        }
        hasConnectedOnceRef.current = true;

        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }));
          }
        }, 10000);
      };

      ws.onmessage = (event) => {
        try {
          const payload: RealtimeEvent = JSON.parse(event.data);

          if (payload.event_id) {
            if (seenEventIdsRef.current.has(payload.event_id)) return;
            seenEventIdsRef.current.add(payload.event_id);
            if (seenEventIdsRef.current.size > 200) {
              const items = Array.from(seenEventIdsRef.current);
              seenEventIdsRef.current = new Set(items.slice(-100));
            }
          }

          if (payload.event_type !== 'HEARTBEAT') {
            onEventRef.current(payload);
          }
        } catch (err) {
          console.error('Dashboard WebSocket parse error:', err);
        }
      };

      ws.onclose = (event) => {
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

        if (event.code === 4401 || event.code === 4403) {
          setStatus('disconnected');
          return;
        }

        // Skip the 'disconnected' flash — go straight to 'reconnecting'
        setStatus('reconnecting');

        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
        reconnectAttemptRef.current += 1;

        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      };
    } catch (err) {
      console.error('Failed to initialize Dashboard WebSocket:', err);
      setStatus('disconnected');
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) {
        try {
          wsRef.current.close(1000, 'Component unmounted');
        } catch {}
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { status };
}
