import { useState, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Inbox, Search, AlertTriangle, CalendarClock, Play } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { conversations as convApi, handoffs as handoffApi, followups as followupApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import { formatDistanceToNow } from 'date-fns';
import { getConversationStatus, statusToBadgeVariant } from '../utils/conversationStatus';
import './Conversations.css';

const FILTERS = [
  { id: 'all',       label: 'All' },
  { id: 'escalated', label: 'Needs Human', icon: AlertTriangle },
  { id: 'followups', label: 'Follow-up Due', icon: CalendarClock },
];

export default function Conversations() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialFilter = searchParams.get('filter') || 'all';
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState(initialFilter);
  const [resumingId, setResumingId] = useState(null);

  const { data, loading, refetch } = useApi(() => convApi.list(), []);
  const { data: escalatedData, loading: escLoading, refetch: refetchEsc } = useApi(
    () => handoffApi.list(), []
  );
  const { data: followupData, loading: fuLoading } = useApi(
    () => followupApi.list(), []
  );

  const conversations = data?.conversations || [];
  const escalatedQueue = escalatedData?.queue || [];
  const followups = followupData?.followups || [];

  // Merge escalated contact IDs for badge
  const escalatedIds = new Set(escalatedQueue.map(h => h.contact_id));
  const followupIds = new Set(followups.map(f => f.contact_id));

  // Build the view based on active filter
  const viewItems = useMemo(() => {
    let items = conversations;
    if (search) {
      const q = search.toLowerCase();
      items = items.filter(c =>
        (c.name || '').toLowerCase().includes(q) ||
        (c.phone || '').includes(q)
      );
    }
    if (filter === 'escalated') {
      items = items.filter(c => escalatedIds.has(c.contact_id));
    } else if (filter === 'followups') {
      items = items.filter(c => followupIds.has(c.contact_id));
    }
    return items;
  }, [conversations, search, filter, escalatedIds, followupIds]);

  async function handleResume(contactId, e) {
    e.stopPropagation();
    setResumingId(contactId);
    try {
      await handoffApi.resume(contactId, 'Resumed from inbox');
      refetch();
      refetchEsc();
    } catch { /* ignore */ }
    finally { setResumingId(null); }
  }

  function handleFilterChange(newFilter) {
    setFilter(newFilter);
    if (newFilter === 'all') {
      searchParams.delete('filter');
    } else {
      searchParams.set('filter', newFilter);
    }
    setSearchParams(searchParams, { replace: true });
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader title="Inbox" description="All WhatsApp conversations" />

      {/* Filter tabs */}
      <div className="inbox-filters">
        {FILTERS.map(f => {
          const count = f.id === 'escalated' ? escalatedQueue.length
            : f.id === 'followups' ? followups.length : 0;
          const Icon = f.icon;
          return (
            <button
              key={f.id}
              className={`inbox-filter-btn ${filter === f.id ? 'inbox-filter-btn--active' : ''}`}
              onClick={() => handleFilterChange(f.id)}
            >
              {Icon && <Icon size={14} />}
              <span>{f.label}</span>
              {count > 0 && <span className="inbox-filter-count">{count}</span>}
            </button>
          );
        })}
      </div>

      <div className="conv-search-bar">
        <Search size={16} />
        <input
          type="text"
          placeholder="Search by name or phone..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {viewItems.length === 0 ? (
        <EmptyState
          icon={filter === 'escalated' ? AlertTriangle : filter === 'followups' ? CalendarClock : Inbox}
          title={
            filter === 'escalated' ? 'All clear!'
            : filter === 'followups' ? 'All caught up!'
            : 'No conversations'
          }
          description={
            filter === 'escalated' ? 'No conversations are waiting for a human reply right now.'
            : filter === 'followups' ? 'No contacts need follow-up right now.'
            : search ? 'No matches for your search.' : 'Conversations will appear once customers message you.'
          }
        />
      ) : (
        <div className="conv-list">
          {viewItems.map(c => {
            const isEscalated = escalatedIds.has(c.contact_id);
            const isFollowup = followupIds.has(c.contact_id);
            const escalation = isEscalated ? escalatedQueue.find(h => h.contact_id === c.contact_id) : null;
            const followup = isFollowup ? followups.find(f => f.contact_id === c.contact_id) : null;

            return (
              <div
                key={c.contact_id}
                className={`conv-item ${isEscalated ? 'conv-item--escalated' : ''} ${isFollowup && !isEscalated ? 'conv-item--followup' : ''}`}
                onClick={() => navigate(`/inbox/${c.contact_id}`)}
              >
                <div className="conv-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                <div className="conv-body">
                  <div className="conv-top">
                    <span className="conv-name">{c.name || 'Unknown'}</span>
                    <span className="conv-time">
                      {c.last_time ? formatDistanceToNow(new Date(c.last_time), { addSuffix: true }) : ''}
                    </span>
                  </div>
                  <div className="conv-bottom">
                    <span className="conv-preview truncate">
                      {c.last_direction === 'outbound' && (
                        <span className="conv-preview-prefix">
                          {c.last_sender === 'human' ? 'You: ' : 'AI: '}
                        </span>
                      )}
                      {c.last_message || 'No messages yet'}
                    </span>
                    <div className="conv-badges">
                      {isEscalated ? (
                        <Badge variant="orange" size="sm"><AlertTriangle size={10} /> Needs human</Badge>
                      ) : (() => {
                        const s = getConversationStatus({
                          botOn: c.bot_mode !== false,
                          lastDir: c.last_direction,
                          lastSender: c.last_sender,
                          lastTime: c.last_time,
                        });
                        return (
                          <Badge
                            variant={statusToBadgeVariant(s.tone)}
                            size="sm"
                            dot={s.animated}
                            title={s.label}
                          >
                            {s.label}
                          </Badge>
                        );
                      })()}
                      {isFollowup && !isEscalated && (
                        <Badge variant="warning" size="sm"><CalendarClock size={10} /> Follow-up</Badge>
                      )}
                      <Badge variant="default" size="sm">{c.stage}</Badge>
                    </div>
                  </div>
                  {/* Escalation reason */}
                  {isEscalated && escalation?.reason && (
                    <div className="conv-escalation-reason">
                      <AlertTriangle size={11} />
                      <span>{escalation.reason}</span>
                      <Button
                        size="sm"
                        variant="success"
                        icon={Play}
                        loading={resumingId === c.contact_id}
                        onClick={(e) => handleResume(c.contact_id, e)}
                      >
                        Turn Bot On
                      </Button>
                    </div>
                  )}
                  {/* Follow-up info */}
                  {isFollowup && !isEscalated && followup && (
                    <div className="conv-followup-info">
                      <CalendarClock size={11} />
                      <span>{followup.days_since_contact} days since last contact</span>
                      {followup.deal_value > 0 && <Badge variant="success" size="sm">₹{followup.deal_value.toLocaleString('en-IN')}</Badge>}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
