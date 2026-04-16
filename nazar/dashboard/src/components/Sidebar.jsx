import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Inbox, Users, Megaphone,
  BarChart3, Settings, Zap, BookOpen, Wifi, WifiOff, Brain,
  CreditCard, UsersRound, FileText,
  LogOut, ChevronDown, ChevronRight,
} from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { handoffs as handoffApi, setup as setupApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useNotifications } from './NotificationProvider';
import './Sidebar.css';

const PRIMARY_ITEMS = [
  { path: '/',              icon: LayoutDashboard, label: 'Home' },
  { path: '/inbox',         icon: Inbox,           label: 'Inbox',      badgeType: 'unread' },
  { path: '/contacts',      icon: Users,           label: 'Contacts' },
  { path: '/campaigns',     icon: Megaphone,       label: 'Campaigns' },
  { path: '/reports',       icon: BarChart3,        label: 'Reports' },
];

const SETTINGS_ITEMS = [
  { path: '/bot-setup',     icon: Brain,       label: 'Bot Setup' },
  { path: '/knowledge',     icon: BookOpen,    label: 'Knowledge Base' },
  { path: '/templates',     icon: FileText,    label: 'Templates' },
  { path: '/team',          icon: UsersRound,  label: 'Team' },
  { path: '/billing',       icon: CreditCard,  label: 'Billing' },
  { path: '/settings',      icon: Settings,    label: 'Settings' },
];

export default function Sidebar() {
  const { data } = useApi(() => handoffApi.stats(), [], { initialData: {} });
  const { data: statusData } = useApi(() => setupApi.status(), [], { initialData: {} });
  const { user, logout } = useAuth();
  const { unreadCount } = useNotifications();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const escalatedCount = data?.currently_in_queue || 0;
  const llmOk = statusData?.any_llm_configured || false;
  const waOk = statusData?.whatsapp?.configured || false;

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <Zap size={20} />
          <span>Nazar</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section">
          {PRIMARY_ITEMS.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.badgeType === 'unread' && (unreadCount > 0 || escalatedCount > 0) && (
                <span className="nav-badge nav-badge--primary">
                  {(unreadCount + escalatedCount) > 99 ? '99+' : unreadCount + escalatedCount}
                </span>
              )}
            </NavLink>
          ))}
        </div>

        <div className="nav-section nav-section-bottom">
          {/* Collapsible Settings & Tools */}
          <button
            className="nav-section-toggle"
            onClick={() => setSettingsOpen(!settingsOpen)}
          >
            <span className="nav-section-title">Settings & Tools</span>
            {settingsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {settingsOpen && (
            <div className="nav-section-collapsible">
              {SETTINGS_ITEMS.map(item => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                  <item.icon size={18} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          )}

          {/* Legal links */}
          <div className="nav-legal">
            <NavLink to="/privacy" className="nav-legal-link">Privacy</NavLink>
            <span className="nav-legal-sep">·</span>
            <NavLink to="/terms" className="nav-legal-link">Terms</NavLink>
          </div>

          {/* Connection status indicators */}
          <div className="sidebar-status">
            <div className={`status-pill ${llmOk ? 'status-pill--ok' : 'status-pill--off'}`}>
              <Brain size={12} />
              <span>{llmOk ? 'AI Active' : 'No LLM Key'}</span>
            </div>
            <div className={`status-pill ${waOk ? 'status-pill--ok' : 'status-pill--warn'}`}>
              {waOk ? <Wifi size={12} /> : <WifiOff size={12} />}
              <span>{waOk ? 'WhatsApp' : 'Sim Only'}</span>
            </div>
          </div>

          {/* User info & logout */}
          {user && (
            <div className="sidebar-user">
              <div className="sidebar-user-avatar">
                {(user.name || user.email || '?')[0].toUpperCase()}
              </div>
              <div className="sidebar-user-info">
                <span className="sidebar-user-name">{user.name || user.email}</span>
                <span className="sidebar-user-role">{user.role || 'admin'}</span>
              </div>
              <button className="sidebar-logout" onClick={logout} title="Sign out">
                <LogOut size={14} />
              </button>
            </div>
          )}
        </div>
      </nav>
    </aside>
  );
}
