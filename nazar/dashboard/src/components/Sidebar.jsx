import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, MessageSquare, Users, GitBranch,
  HandMetal, CalendarClock, FileText,
  Settings, Zap, BookOpen, Wifi, WifiOff, Brain,
  BarChart3, CreditCard, UsersRound, Rocket,
  Shield, FileCheck, LogOut, Megaphone,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { handoffs as handoffApi, setup as setupApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import './Sidebar.css';

const NAV_ITEMS = [
  { path: '/',             icon: LayoutDashboard, label: 'Overview' },
  { path: '/conversations', icon: MessageSquare,   label: 'Conversations' },
  { path: '/contacts',     icon: Users,            label: 'Contacts' },
  { path: '/pipeline',     icon: GitBranch,        label: 'Pipeline' },
  { path: '/handoffs',     icon: HandMetal,        label: 'Handoffs',    badge: true },
  { path: '/followups',    icon: CalendarClock,    label: 'Follow-ups' },
  { path: '/campaigns',    icon: Megaphone,        label: 'Campaigns' },
  { path: '/templates',    icon: FileText,         label: 'Templates' },
  { path: '/analytics',    icon: BarChart3,        label: 'Analytics' },
];

const BOTTOM_ITEMS = [
  { path: '/onboarding',   icon: Rocket,     label: 'Setup Wizard' },
  { path: '/knowledge',    icon: BookOpen,    label: 'Knowledge Base' },
  { path: '/team',         icon: UsersRound,  label: 'Team' },
  { path: '/billing',      icon: CreditCard,  label: 'Billing' },
  { path: '/settings',     icon: Settings,    label: 'Settings' },
];

export default function Sidebar() {
  const { data } = useApi(() => handoffApi.stats(), [], { initialData: {} });
  const { data: statusData } = useApi(() => setupApi.status(), [], { initialData: {} });
  const { user, logout } = useAuth();
  const handoffCount = data?.currently_in_queue || 0;

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
          <span className="nav-section-title">Main</span>
          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.badge && handoffCount > 0 && (
                <span className="nav-badge">{handoffCount}</span>
              )}
            </NavLink>
          ))}
        </div>

        <div className="nav-section nav-section-bottom">
          <span className="nav-section-title">System</span>
          {BOTTOM_ITEMS.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          ))}

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
