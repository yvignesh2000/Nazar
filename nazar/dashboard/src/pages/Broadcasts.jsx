import { useState } from 'react';
import { Send, History } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { broadcasts as broadcastApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import { format } from 'date-fns';
import './Broadcasts.css';

export default function Broadcasts() {
  const { data, loading, refetch } = useApi(() => broadcastApi.history(), []);
  const [sending, setSending] = useState(false);
  const [form, setForm] = useState({ message: '', filter_stage: '', filter_tag: '' });

  async function handleSend(e) {
    e.preventDefault();
    if (!form.message.trim()) return;
    setSending(true);
    try {
      await broadcastApi.send(form);
      setForm({ message: '', filter_stage: '', filter_tag: '' });
      refetch();
    } catch (err) {
      alert(err.message);
    } finally {
      setSending(false);
    }
  }

  if (loading) return <Spinner />;

  const history = data?.history || [];

  return (
    <div className="page-content">
      <PageHeader title="Broadcasts" description="Send messages to multiple contacts" />

      <form className="broadcast-form" onSubmit={handleSend}>
        <textarea
          placeholder="Type your broadcast message..."
          value={form.message}
          onChange={e => setForm({ ...form, message: e.target.value })}
          rows={3}
        />
        <div className="broadcast-filters">
          <input placeholder="Filter by stage (optional)" value={form.filter_stage} onChange={e => setForm({ ...form, filter_stage: e.target.value })} />
          <input placeholder="Filter by tag (optional)" value={form.filter_tag} onChange={e => setForm({ ...form, filter_tag: e.target.value })} />
          <Button type="submit" icon={Send} loading={sending}>Send Broadcast</Button>
        </div>
      </form>

      <h2 className="section-title">History</h2>
      {history.length === 0 ? (
        <EmptyState icon={History} title="No broadcasts yet" description="Your broadcast history will appear here." />
      ) : (
        <div className="broadcast-history">
          {history.map((b, i) => (
            <div key={i} className="broadcast-item">
              <div className="broadcast-msg">{b.message}</div>
              <div className="broadcast-meta">
                <span>Sent: {b.sent || 0}</span>
                <span>Failed: {b.failed || 0}</span>
                <span>{b.timestamp ? format(new Date(b.timestamp), 'MMM d, h:mm a') : ''}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
