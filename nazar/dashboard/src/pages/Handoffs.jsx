import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { HandMetal, AlertTriangle, Clock, CheckCircle2, Key, Brain, Bot, User, Play, MessageSquare, History, CalendarClock, ArrowRight } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { handoffs as handoffApi, followups as followupApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import { formatDistanceToNow, format } from 'date-fns';
import './Handoffs.css';

const METHOD_ICONS = {
  keyword: { icon: Key, label: 'Keyword', variant: 'warning' },
  ai_intent: { icon: Brain, label: 'AI Intent', variant: 'primary' },
  ai_response: { icon: Bot, label: 'AI Response', variant: 'primary' },
  manual: { icon: User, label: 'Manual', variant: 'gray' },
};

const EVENT_COLORS = {
  triggered: 'var(--color-orange-500)',
  resumed: 'var(--color-success-500)',
  human_responded: 'var(--color-primary-500)',
};

export default function Handoffs() {
  const [tab, setTab] = useState('queue');
  const navigate = useNavigate();

  const { data: queueData, loading: queueLoading, refetch: refetchQueue } = useApi(
    () => handoffApi.list(), []
  );
  const { data: statsData, refetch: refetchStats } = useApi(
    () => handoffApi.stats(), [], { initialData: {} }
  );
  const { data: historyData, loading: historyLoading, refetch: refetchHistory } = useApi(
    () => handoffApi.history(), [], { enabled: tab === 'history' }
  );
  const { data: followupData, loading: followupsLoading } = useApi(
    () => followupApi.list(), [], { enabled: tab === 'followups' }
  );

  const [resumingId, setResumingId] = useState(null);

  async function handleResume(contactId) {
    setResumingId(contactId);
    try {
      await handoffApi.resume(contactId, 'Resumed from dashboard');
      refetchQueue();
      refetchStats();
      if (tab === 'history') refetchHistory();
    } catch (err) {
      console.error('Resume failed:', err);
    } finally {
      setResumingId(null);
    }
  }

  const queue = queueData?.queue || [];
  const followups = followupData?.followups || [];
  const followupCount = statsData?.followup_count || 0;

  return (
    <div className="page-content">
      <PageHeader
        title="Attention Needed"
        description="Escalated conversations and contacts needing follow-up"
      />

      {/* Stats */}
      <div className="stat-grid stat-grid--4">
        <StatCard
          icon={AlertTriangle}
          label="Escalated"
          value={statsData?.currently_in_queue || 0}
          variant="orange"
        />
        <StatCard
          icon={CalendarClock}
          label="Need Follow-up"
          value={followupCount}
          variant="warning"
        />
        <StatCard
          icon={HandMetal}
          label="Total Handoffs"
          value={statsData?.total_handoffs || 0}
          variant="default"
        />
        <StatCard
          icon={CheckCircle2}
          label="Resolved"
          value={statsData?.total_resumes || 0}
          variant="success"
        />
      </div>

      {/* Tabs */}
      <div className="tabs">
        <button className={`tab ${tab === 'queue' ? 'tab--active' : ''}`} onClick={() => setTab('queue')}>
          <HandMetal size={15} /> Escalated {queue.length > 0 && <span className="tab-count">{queue.length}</span>}
        </button>
        <button className={`tab ${tab === 'followups' ? 'tab--active' : ''}`} onClick={() => setTab('followups')}>
          <CalendarClock size={15} /> Follow-ups {followupCount > 0 && <span className="tab-count tab-count--yellow">{followupCount}</span>}
        </button>
        <button className={`tab ${tab === 'history' ? 'tab--active' : ''}`} onClick={() => setTab('history')}>
          <History size={15} /> History
        </button>
      </div>

      {/* Escalated Queue Tab */}
      {tab === 'queue' && (
        queueLoading ? <Spinner /> : queue.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title="All clear!"
            description="No conversations are waiting for human attention right now."
          />
        ) : (
          <div className="handoff-grid">
            {queue.map(h => {
              const method = METHOD_ICONS[h.detection_method] || METHOD_ICONS.manual;
              const MethodIcon = method.icon;
              return (
                <div key={h.contact_id} className="handoff-card">
                  <div className="handoff-card-header">
                    <div className="handoff-contact">
                      <div className="handoff-avatar">{(h.contact_name || '?')[0].toUpperCase()}</div>
                      <div>
                        <div className="handoff-name">{h.contact_name || 'Unknown'}</div>
                        <div className="handoff-phone">{h.contact_phone || h.contact_id}</div>
                      </div>
                    </div>
                    <Badge variant={method.variant}>
                      <MethodIcon size={12} /> {method.label}
                    </Badge>
                  </div>

                  <div className="handoff-reason">{h.reason || 'No reason given'}</div>

                  {h.message_excerpt && (
                    <div className="handoff-excerpt">"{h.message_excerpt}"</div>
                  )}

                  <div className="handoff-meta">
                    <span className="handoff-time">
                      <Clock size={12} />
                      {h.triggered_at ? formatDistanceToNow(new Date(h.triggered_at), { addSuffix: true }) : 'Unknown'}
                    </span>
                    {h.human_responded && (
                      <Badge variant="success" size="sm">
                        <CheckCircle2 size={10} /> Human replied
                      </Badge>
                    )}
                  </div>

                  <div className="handoff-card-actions">
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={MessageSquare}
                      onClick={() => navigate(`/conversations/${h.contact_id}`)}
                    >
                      Open Chat
                    </Button>
                    <Button
                      size="sm"
                      variant="success"
                      icon={Play}
                      loading={resumingId === h.contact_id}
                      onClick={() => handleResume(h.contact_id)}
                    >
                      Resume Bot
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}

      {/* Follow-ups Tab */}
      {tab === 'followups' && (
        followupsLoading ? <Spinner /> : followups.length === 0 ? (
          <EmptyState icon={CalendarClock} title="All caught up!" description="No contacts need follow-up right now." />
        ) : (
          <div className="handoff-grid">
            {followups.map(f => (
              <div key={f.contact_id} className="handoff-card followup-card-styled">
                <div className="handoff-card-header">
                  <div className="handoff-contact">
                    <div className="handoff-avatar handoff-avatar--yellow">{(f.name || '?')[0].toUpperCase()}</div>
                    <div>
                      <div className="handoff-name">{f.name || 'Unknown'}</div>
                      <div className="handoff-phone">{f.phone}</div>
                    </div>
                  </div>
                  <Badge variant={f.priority === 'high' ? 'danger' : f.priority === 'medium' ? 'warning' : 'default'}>
                    {f.priority} priority
                  </Badge>
                </div>

                <div className="followup-detail-row">
                  <span className="followup-days">{f.days_since_contact} days since last contact</span>
                  {f.stage && <Badge variant="default" size="sm">{f.stage}</Badge>}
                  {f.deal_value > 0 && <Badge variant="success" size="sm">₹{f.deal_value.toLocaleString('en-IN')}</Badge>}
                </div>

                <div className="handoff-card-actions">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={MessageSquare}
                    onClick={() => navigate(`/conversations/${f.contact_id}`)}
                  >
                    Open Chat
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {/* History Tab */}
      {tab === 'history' && (
        historyLoading ? <Spinner /> : (
          <div className="history-list">
            {(historyData?.history || []).length === 0 ? (
              <EmptyState icon={History} title="No history" description="Handoff events will appear here." />
            ) : (
              (historyData.history).map((event, i) => (
                <div key={i} className="history-item">
                  <div
                    className="history-dot"
                    style={{ background: EVENT_COLORS[event.event] || 'var(--color-gray-400)' }}
                  />
                  <div className="history-body">
                    <div className="history-header">
                      <span className="history-event">{event.event}</span>
                      <Badge variant={event.event === 'triggered' ? 'orange' : event.event === 'resumed' ? 'success' : 'primary'} size="sm">
                        {event.event}
                      </Badge>
                    </div>
                    <div className="history-detail">
                      <strong>{event.contact_name || event.contact_id}</strong>
                      {event.reason && <> &mdash; {event.reason}</>}
                    </div>
                    <div className="history-time">
                      {event.timestamp ? format(new Date(event.timestamp), 'MMM d, h:mm a') : ''}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )
      )}
    </div>
  );
}
