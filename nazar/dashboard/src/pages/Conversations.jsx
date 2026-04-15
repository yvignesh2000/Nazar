import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Search, Bot, User } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { conversations as convApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import { formatDistanceToNow } from 'date-fns';
import './Conversations.css';

export default function Conversations() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const { data, loading } = useApi(() => convApi.list(), []);

  const conversations = (data?.conversations || []).filter(c =>
    !search || (c.name || '').toLowerCase().includes(search.toLowerCase()) ||
    (c.phone || '').includes(search)
  );

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader title="Conversations" description="All WhatsApp conversations" />

      <div className="conv-search-bar">
        <Search size={16} />
        <input
          type="text"
          placeholder="Search by name or phone..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {conversations.length === 0 ? (
        <EmptyState
          icon={MessageSquare}
          title="No conversations"
          description={search ? 'No matches for your search.' : 'Conversations will appear once customers message you.'}
        />
      ) : (
        <div className="conv-list">
          {conversations.map(c => (
            <div
              key={c.contact_id}
              className="conv-item"
              onClick={() => navigate(`/conversations/${c.contact_id}`)}
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
                  <span className="conv-preview truncate">{c.last_message || 'No messages yet'}</span>
                  <div className="conv-badges">
                    {c.bot_mode === false && (
                      <Badge variant="orange" size="sm"><User size={10} /> Human</Badge>
                    )}
                    <Badge variant="default" size="sm">{c.stage}</Badge>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
