import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, MessageSquare, DollarSign, TrendingUp, Zap, ArrowRight,
  CheckCircle2, Circle, SkipForward, Brain, BookOpen, Wifi, UserPlus,
  Building2, Rocket, CalendarClock, AlertTriangle, Inbox, Megaphone,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import {
  overview as overviewApi, handoffs as handoffApi,
  followups as followupApi, activity as activityApi,
  onboarding as onboardingApi,
} from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Spinner from '../components/ui/Spinner';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { formatDistanceToNow } from 'date-fns';
import './Overview.css';

/* ── Inline Setup Checklist (shown for new users) ──────────────── */
const STEP_ICONS = {
  account_created: Building2,
  business_info: Building2,
  knowledge_base: BookOpen,
  whatsapp_connect: Wifi,
  llm_configured: Brain,
  first_contact: Users,
  first_message: MessageSquare,
  team_invited: UserPlus,
};

const STEP_LINKS = {
  business_info: '/settings',
  knowledge_base: '/knowledge',
  whatsapp_connect: '/settings',
  llm_configured: '/settings',
  first_contact: '/contacts',
  first_message: '/inbox',
  team_invited: '/team',
};

const STEP_DESCRIPTIONS = {
  account_created: 'Your workspace and admin account are set up.',
  business_info: 'Add your business name and configure how the bot sounds.',
  knowledge_base: 'Teach the AI about your products, services, and FAQs.',
  whatsapp_connect: 'Connect your WhatsApp Business number (or skip to use simulation).',
  llm_configured: 'Add an AI provider key so the bot can reply to customers.',
  first_contact: 'Import or add your first customer contact.',
  first_message: 'Send a test message to see the full pipeline in action.',
  team_invited: 'Invite a team member or skip for now.',
};

function InlineSetupChecklist({ onboardingData, onRefetch }) {
  const navigate = useNavigate();
  const [acting, setActing] = useState(null);

  const state = onboardingData || {};
  const steps = (state.steps_list || []).map(s => ({
    step_id: s.id ?? s.step_id,
    name: s.title ?? s.name ?? s.step_id,
    status: s.done ? 'done' : s.skipped ? 'skipped' : 'pending',
    skippable: s.skippable,
  }));
  const progress = state.progress_pct || 0;
  const completedCount = steps.filter(s => s.status === 'done' || s.status === 'skipped').length;

  async function handleDone(stepId) {
    setActing(stepId);
    try {
      await onboardingApi.markDone(stepId);
      onRefetch();
    } catch { /* ignore */ }
    finally { setActing(null); }
  }

  async function handleSkip(stepId) {
    setActing(stepId);
    try {
      await onboardingApi.skip(stepId);
      onRefetch();
    } catch { /* ignore */ }
    finally { setActing(null); }
  }

  return (
    <div className="setup-inline">
      <div className="setup-inline-header">
        <div>
          <h2 className="setup-inline-title">
            <Rocket size={20} /> Let's get Nazar ready for your business
          </h2>
          <p className="setup-inline-subtitle">
            Complete these steps to start engaging customers on WhatsApp with AI.
          </p>
        </div>
        <div className="setup-inline-progress">
          <div className="setup-progress-ring">
            <svg viewBox="0 0 36 36" className="setup-ring-svg">
              <path
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                fill="none"
                stroke="var(--color-gray-200)"
                strokeWidth="3"
              />
              <path
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                fill="none"
                stroke="var(--color-primary-500)"
                strokeWidth="3"
                strokeDasharray={`${progress}, 100`}
                strokeLinecap="round"
              />
            </svg>
            <span className="setup-ring-text">{completedCount}/{steps.length}</span>
          </div>
        </div>
      </div>

      <div className="setup-inline-steps">
        {steps.map((step, index) => {
          const Icon = STEP_ICONS[step.step_id] || Circle;
          const isDone = step.status === 'done';
          const isSkipped = step.status === 'skipped';
          const isPending = step.status === 'pending';
          const isNext = isPending && index === steps.findIndex(s => s.status === 'pending');

          return (
            <div
              key={step.step_id}
              className={`setup-step ${isDone ? 'setup-step--done' : ''} ${isSkipped ? 'setup-step--skipped' : ''} ${isNext ? 'setup-step--next' : ''}`}
            >
              <div className="setup-step-icon">
                {isDone ? <CheckCircle2 size={18} /> : isSkipped ? <SkipForward size={16} /> : <span className="setup-step-num">{index + 1}</span>}
              </div>
              <div className="setup-step-body">
                <span className="setup-step-name">{step.name}</span>
                <span className="setup-step-desc">{STEP_DESCRIPTIONS[step.step_id] || ''}</span>
              </div>
              {isPending && (
                <div className="setup-step-actions">
                  {STEP_LINKS[step.step_id] && (
                    <Button size="sm" icon={ArrowRight} onClick={() => navigate(STEP_LINKS[step.step_id])}>
                      Go
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" loading={acting === step.step_id} onClick={() => handleDone(step.step_id)}>
                    Done
                  </Button>
                  {step.skippable !== false && (
                    <button className="setup-skip-btn" onClick={() => handleSkip(step.step_id)}>Skip</button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Quick Actions for empty-ish product ────────────────────────── */
function QuickActions({ hasContacts, hasCampaigns }) {
  const navigate = useNavigate();

  const actions = [];
  if (!hasContacts) {
    actions.push({ icon: Users, label: 'Add your contacts', desc: 'Import a CSV or add contacts manually', to: '/contacts', color: 'var(--color-primary-500)' });
  }
  if (hasContacts && !hasCampaigns) {
    actions.push({ icon: Megaphone, label: 'Send your first campaign', desc: 'Reach your contacts at scale with templates', to: '/campaigns', color: 'var(--color-success-500)' });
  }
  actions.push({ icon: Inbox, label: 'Open Inbox', desc: 'View and reply to customer conversations', to: '/inbox', color: 'var(--color-primary-500)' });

  if (actions.length === 0) return null;

  return (
    <div className="quick-actions">
      {actions.map((a, i) => (
        <button key={i} className="quick-action-card" onClick={() => navigate(a.to)}>
          <div className="quick-action-icon" style={{ background: `${a.color}15`, color: a.color }}>
            <a.icon size={22} />
          </div>
          <div className="quick-action-text">
            <span className="quick-action-label">{a.label}</span>
            <span className="quick-action-desc">{a.desc}</span>
          </div>
          <ArrowRight size={16} className="quick-action-arrow" />
        </button>
      ))}
    </div>
  );
}

/* ── Main Overview ──────────────────────────────────────────────── */
export default function Overview() {
  const { data, loading } = useApi(() => overviewApi.get(), []);
  const { data: handoffData } = useApi(() => handoffApi.stats(), []);
  const { data: followupData } = useApi(() => followupApi.list(), []);
  const { data: activityData } = useApi(() => activityApi.list(), []);
  const { data: onboardingData, loading: obLoading, refetch: refetchOb } = useApi(
    () => onboardingApi.get(), []
  );

  if (loading || obLoading) return <Spinner />;

  const o = data || {};
  const stats = o.stats || {};
  const recentContacts = o.recent_contacts || [];
  const isSetupComplete = onboardingData?.is_complete ?? onboardingData?.completed;
  const hasContacts = (stats.total_contacts || 0) > 0;
  const escalatedCount = handoffData?.currently_in_queue || 0;
  const followupCount = followupData?.followups?.length || 0;

  return (
    <div className="page-content">
      <PageHeader title="Home" description="Your business at a glance" />

      {/* Inline Setup Wizard — shown until complete */}
      {!isSetupComplete && (
        <InlineSetupChecklist onboardingData={onboardingData} onRefetch={refetchOb} />
      )}

      {/* Quick Actions — contextual CTAs */}
      {isSetupComplete && (
        <QuickActions
          hasContacts={hasContacts}
          hasCampaigns={(stats.total_campaigns || 0) > 0}
        />
      )}

      {/* Needs Attention Banner */}
      {(escalatedCount > 0 || followupCount > 0) && (
        <div className="attention-banner">
          {escalatedCount > 0 && (
            <a href="/inbox?filter=escalated" className="attention-item attention-item--urgent">
              <AlertTriangle size={16} />
              <span><strong>{escalatedCount}</strong> conversation{escalatedCount !== 1 ? 's' : ''} need{escalatedCount === 1 ? 's' : ''} a human reply</span>
              <ArrowRight size={14} />
            </a>
          )}
          {followupCount > 0 && (
            <a href="/inbox?filter=followups" className="attention-item attention-item--warning">
              <CalendarClock size={16} />
              <span><strong>{followupCount}</strong> contact{followupCount !== 1 ? 's' : ''} need follow-up</span>
              <ArrowRight size={14} />
            </a>
          )}
        </div>
      )}

      {/* Stats — always shown */}
      <div className="stat-grid">
        <StatCard icon={Users} label="Total Contacts" value={stats.total_contacts || 0} variant="default" />
        <StatCard icon={MessageSquare} label="Active Leads" value={stats.active_leads || 0} variant="success" />
        <StatCard icon={DollarSign} label="Pipeline Value" value={`₹${(stats.pipeline_value || 0).toLocaleString('en-IN')}`} variant="warning" />
        <StatCard icon={TrendingUp} label="Revenue" value={`₹${(stats.total_revenue || 0).toLocaleString('en-IN')}`} variant="success" />
      </div>

      <div className="overview-panels">
        {/* Recent Activity */}
        <div className="panel">
          <h2 className="panel-title">Recent Activity</h2>
          <div className="panel-body">
            {(activityData?.activities || []).slice(0, 8).map((a, i) => (
              <div key={i} className="activity-item">
                <div className="activity-dot" />
                <div className="activity-text">
                  <span className="activity-name">{a.contact_name}</span>
                  <span className="activity-detail">{a.detail}</span>
                </div>
                <span className="activity-time">
                  {a.time ? formatDistanceToNow(new Date(a.time), { addSuffix: true }) : ''}
                </span>
              </div>
            ))}
            {(!activityData?.activities || activityData.activities.length === 0) && (
              <p className="panel-empty">No recent activity</p>
            )}
          </div>
        </div>

        {/* Recent Contacts */}
        <div className="panel">
          <h2 className="panel-title">Recent Contacts</h2>
          <div className="panel-body">
            {recentContacts.slice(0, 8).map(c => (
              <div key={c.contact_id} className="contact-row">
                <div className="contact-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                <div className="contact-info">
                  <span className="contact-name">{c.name || 'Unknown'}</span>
                  <span className="contact-phone">{c.phone}</span>
                </div>
                <Badge variant={c.stage === 'Won' ? 'success' : c.stage === 'Lost' ? 'danger' : 'default'}>
                  {c.stage}
                </Badge>
              </div>
            ))}
            {recentContacts.length === 0 && (
              <p className="panel-empty">No contacts yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
