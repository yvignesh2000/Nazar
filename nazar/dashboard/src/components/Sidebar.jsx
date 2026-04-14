import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, MessageSquare, Users, GitBranch,
  HandMetal, CalendarClock, Send, FileText,
  Settings, Zap, BookOpen,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { handoffs as handoffApi } from '../api/client';
import './Sidebar.css';

const NAV_ITEMS = [
  { path: '/',             icon: LayoutDashboard, label: 'Overview' },
  { path: '/conversations', icon: MessageSquare,   label: 'Conversations' },
  { path: '/contacts',     icon: Users,            label: 'Contacts' },
  { path: '/pipeline',     icon: GitBranch,        label: 'Pipeline' },
  { path: '/handoffs',     icon: HandMetal,        label: 'Handoffs',    badge: true },
  { path: '/followups',    icon: CalendarClock,    label: 'Follow-ups' },
  { path: '/broadcasts',   icon: Send,             label: 'Broadcasts' },
  { path: '/templates',    icon: FileText,         label: 'Templates' },
];

const BOTTOM_ITEMS = [
  { path: '/knowledge',    icon: BookOpen,   label: 'Knowledge Base' },
  { path: '/settings',     icon: Settings,   label: 'Settings' },
];

export default function Sidebar() {
  const { data } = useApi(() => handoffApi.stats(), [], { initialData: {} });
  const handoffCount = data?.in_queue || 0;

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
        </div>
      </nav>
    </aside>
  );
}
