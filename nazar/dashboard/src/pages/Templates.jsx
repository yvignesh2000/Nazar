import { useState } from 'react';
import { FileText, Plus, Trash2, Edit } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { templates as templateApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import './Templates.css';

export default function Templates() {
  const { data, loading, refetch } = useApi(() => templateApi.list(), []);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', body: '', category: 'general' });
  const [creating, setCreating] = useState(false);

  async function handleCreate(e) {
    e.preventDefault();
    if (!form.name || !form.body) return;
    setCreating(true);
    try {
      await templateApi.create(form);
      setShowCreate(false);
      setForm({ name: '', body: '', category: 'general' });
      refetch();
    } catch (err) {
      alert(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this template?')) return;
    await templateApi.delete(id);
    refetch();
  }

  if (loading) return <Spinner />;

  const templates = data?.templates || [];

  return (
    <div className="page-content">
      <PageHeader
        title="Templates"
        description="Reusable message templates"
        actions={<Button icon={Plus} onClick={() => setShowCreate(!showCreate)}>New Template</Button>}
      />

      {showCreate && (
        <form className="template-form" onSubmit={handleCreate}>
          <input placeholder="Template name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
          <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
            <option value="general">General</option>
            <option value="followup">Follow-up</option>
            <option value="welcome">Welcome</option>
            <option value="promotion">Promotion</option>
          </select>
          <textarea placeholder="Template body (use {{name}}, {{company}} for variables)" value={form.body} onChange={e => setForm({ ...form, body: e.target.value })} rows={3} required />
          <div className="template-form-actions">
            <Button type="submit" loading={creating}>Create</Button>
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
          </div>
        </form>
      )}

      {templates.length === 0 ? (
        <EmptyState icon={FileText} title="No templates" description="Create your first reusable message template." />
      ) : (
        <div className="template-grid">
          {templates.map(t => (
            <div key={t.template_id} className="template-card">
              <div className="template-card-header">
                <span className="template-card-name">{t.name}</span>
                <Badge variant="default" size="sm">{t.category}</Badge>
              </div>
              <div className="template-card-body">{t.body}</div>
              <div className="template-card-footer">
                <span className="template-card-usage">Used {t.usage_count || 0} times</span>
                <button className="template-delete" onClick={() => handleDelete(t.template_id)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
