import { useNavigate } from 'react-router-dom';
import { CalendarClock, MessageSquare } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { followups as followupApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Button from '../components/ui/Button';
import Spinner from '../components/ui/Spinner';
import './Followups.css';

export default function Followups() {
  const navigate = useNavigate();
  const { data, loading } = useApi(() => followupApi.list(), []);

  if (loading) return <Spinner />;

  const followups = data?.followups || [];

  return (
    <div className="page-content">
      <PageHeader title="Follow-ups" description="Contacts that need your attention" />

      {followups.length === 0 ? (
        <EmptyState icon={CalendarClock} title="No follow-ups" description="All caught up! No contacts need follow-up right now." />
      ) : (
        <div className="followup-list">
          {followups.map(f => (
            <div key={f.contact_id} className="followup-card">
              <div className="followup-header">
                <div className="followup-avatar">{(f.name || '?')[0].toUpperCase()}</div>
                <div className="followup-info">
                  <span className="followup-name">{f.name || 'Unknown'}</span>
                  <span className="followup-phone">{f.phone}</span>
                </div>
                <Badge variant={f.priority === 'high' ? 'danger' : f.priority === 'medium' ? 'warning' : 'default'}>
                  {f.priority} priority
                </Badge>
              </div>
              <div className="followup-detail">
                <span>{f.days_since_contact} days since last contact</span>
                {f.stage && <Badge variant="default">{f.stage}</Badge>}
                {f.deal_value > 0 && <Badge variant="success" size="sm">₹{f.deal_value.toLocaleString('en-IN')}</Badge>}
              </div>
              <div className="followup-actions">
                <Button size="sm" variant="secondary" icon={MessageSquare} onClick={() => navigate(`/conversations/${f.contact_id}`)}>
                  Open Chat
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
