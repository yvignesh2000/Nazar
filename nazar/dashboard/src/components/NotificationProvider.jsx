/**
 * Nazar — Global Notification Provider
 *
 * Connects the WebSocket real-time events to visible UI notifications.
 * Shows toast messages for new inbound messages, handoff triggers, draft readiness,
 * campaign completion, and contact updates.
 *
 * Also updates the document title with unread count.
 */

import { useState, useEffect, useCallback, createContext, useContext } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import './NotificationProvider.css';
import {
  MessageSquare, AlertTriangle, Sparkles, Send, UserCheck,
  X, CheckCircle, Bell, Volume2, VolumeX,
} from 'lucide-react';

const NotificationContext = createContext({
  unreadCount: 0,
  notifications: [],
  clearAll: () => {},
  soundEnabled: true,
  toggleSound: () => {},
});

export function useNotifications() {
  return useContext(NotificationContext);
}

const MAX_TOASTS = 5;
const TOAST_DURATION_MS = 6000;

const EVENT_CONFIG = {
  new_message: {
    icon: MessageSquare,
    color: 'var(--color-primary-600)',
    bg: 'var(--color-primary-50)',
    getTitle: (data) => `New message from ${data.contact_name || 'Unknown'}`,
    getBody: (data) => data.content?.slice(0, 100) || '',
    sound: true,
    incrementUnread: true,
  },
  handoff_triggered: {
    icon: AlertTriangle,
    color: 'var(--color-orange-600)',
    bg: 'var(--color-orange-50)',
    getTitle: (data) => `Handoff: ${data.contact_name || 'Contact'}`,
    getBody: (data) => data.reason || 'Human handoff triggered',
    sound: true,
    incrementUnread: true,
  },
  bot_resumed: {
    icon: CheckCircle,
    color: 'var(--color-success-600)',
    bg: 'var(--color-success-50)',
    getTitle: (data) => `Bot resumed: ${data.contact_name || 'Contact'}`,
    getBody: (data) => data.reason || 'Bot is now active',
    sound: false,
    incrementUnread: false,
  },
  draft_ready: {
    icon: Sparkles,
    color: 'var(--color-primary-600)',
    bg: 'var(--color-primary-50)',
    getTitle: (data) => `AI Draft ready: ${data.contact_name || 'Contact'}`,
    getBody: (data) => data.draft_preview?.slice(0, 80) || 'New draft to review',
    sound: true,
    incrementUnread: true,
  },
  campaign_completed: {
    icon: Send,
    color: 'var(--color-success-600)',
    bg: 'var(--color-success-50)',
    getTitle: () => 'Campaign completed',
    getBody: (data) => `Sent ${data.sent}/${data.total} — ${data.failed || 0} failed`,
    sound: false,
    incrementUnread: false,
  },
  contact_updated: {
    icon: UserCheck,
    color: 'var(--color-gray-600)',
    bg: 'var(--color-gray-50)',
    getTitle: (data) => `Contact updated`,
    getBody: (data) => {
      const fields = data.fields || {};
      return Object.keys(fields).slice(0, 3).join(', ') + ' changed';
    },
    sound: false,
    incrementUnread: false,
  },
};

// Simple notification sound (data URI - tiny beep)
let audioContext = null;
function playNotificationSound() {
  try {
    if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    osc.connect(gain);
    gain.connect(audioContext.destination);
    osc.frequency.value = 800;
    gain.gain.value = 0.1;
    osc.start();
    osc.stop(audioContext.currentTime + 0.15);
  } catch {
    // Audio not supported
  }
}

export default function NotificationProvider({ children }) {
  const { subscribe, isConnected } = useWebSocket();
  const [toasts, setToasts] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [soundEnabled, setSoundEnabled] = useState(() => {
    const stored = localStorage.getItem('nazar_notification_sound');
    return stored !== 'false';
  });

  // Update document title with unread count
  useEffect(() => {
    const baseTitle = 'Nazar Dashboard';
    document.title = unreadCount > 0 ? `(${unreadCount}) ${baseTitle}` : baseTitle;
  }, [unreadCount]);

  // Auto-remove toasts
  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setTimeout(() => {
      setToasts(prev => prev.slice(1));
    }, TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [toasts]);

  const addToast = useCallback((toast) => {
    setToasts(prev => {
      const next = [...prev, { ...toast, id: Date.now() + Math.random() }];
      return next.slice(-MAX_TOASTS);
    });
  }, []);

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setUnreadCount(0);
    setToasts([]);
  }, []);

  const toggleSound = useCallback(() => {
    setSoundEnabled(prev => {
      const next = !prev;
      localStorage.setItem('nazar_notification_sound', String(next));
      return next;
    });
  }, []);

  // Subscribe to WebSocket events
  useEffect(() => {
    const unsub = subscribe('*', (event) => {
      const config = EVENT_CONFIG[event.type];
      if (!config) return;

      const data = event.data ?? event;

      // Don't show notifications for outbound messages from 'bot' or 'human'
      if (event.type === 'new_message' && data.direction === 'outbound') return;

      addToast({
        type: event.type,
        title: config.getTitle(data),
        body: config.getBody(data),
        icon: config.icon,
        color: config.color,
        bg: config.bg,
        contactId: data.contact_id,
      });

      if (config.incrementUnread) {
        setUnreadCount(c => c + 1);
      }

      if (config.sound && soundEnabled) {
        playNotificationSound();
      }

      // Browser notification (if permission granted)
      if (config.sound && Notification.permission === 'granted') {
        try {
          new Notification(config.getTitle(data), {
            body: config.getBody(data),
            icon: '/favicon.svg',
            tag: `nazar-${event.type}-${data.contact_id || ''}`,
          });
        } catch {
          // Notifications not supported
        }
      }
    });

    return unsub;
  }, [subscribe, addToast, soundEnabled]);

  // Request notification permission on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  return (
    <NotificationContext.Provider value={{
      unreadCount, notifications: toasts, clearAll, soundEnabled, toggleSound,
    }}>
      {children}

      {/* Toast container */}
      <div className="toast-container" aria-live="polite">
        {toasts.map(toast => {
          const Icon = toast.icon;
          return (
            <div
              key={toast.id}
              className="toast-item"
              style={{ '--toast-color': toast.color, '--toast-bg': toast.bg }}
              onClick={() => {
                if (toast.contactId) {
                  window.location.hash = `#/conversations/${toast.contactId}`;
                }
                removeToast(toast.id);
              }}
            >
              <div className="toast-icon">
                <Icon size={16} />
              </div>
              <div className="toast-content">
                <div className="toast-title">{toast.title}</div>
                {toast.body && <div className="toast-body">{toast.body}</div>}
              </div>
              <button
                className="toast-close"
                onClick={(e) => { e.stopPropagation(); removeToast(toast.id); }}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Connection indicator */}
      {!isConnected && (
        <div className="ws-disconnected-bar">
          Reconnecting to server...
        </div>
      )}
    </NotificationContext.Provider>
  );
}
