import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Users, Plus, Search, Trash2, Phone, Building } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { contacts as contactsApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import './Contacts.css';

const STAGE_VARIANTS = {
  New: 'default', Qualified: 'primary', Proposal: 'warning',
  Negotiation: 'orange', Won: 'success', Lost: 'danger',
};

export default function Contacts() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', phone: '', company: '', source: '' });
  const [creating, setCreating] = useState(false);

  const { data, loading, refetch } = useApi(() => contactsApi.list(), []);
  const contacts = (data?.contacts || []).filter(c =>
    !search ||
    (c.name || '').toLowerCase().includes(search.toLowerCase()) ||
    (c.phone || '').includes(search) ||
    (c.company || '').toLowerCase().includes(search.toLowerCase())
  );

  async function handleCreate(e) {
    e.preventDefault();
    if (!form.phone) return;
    setCreating(true);
    try {
      await contactsApi.create(form);
      setShowCreate(false);
      setForm({ name: '', phone: '', company: '', source: '' });
      refetch();
    } catch (err) {
      alert(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id, name) {
    if (!confirm(`Delete ${name || 'this contact'}?`)) return;
    await contactsApi.delete(id);
    refetch();
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Contacts"
        description={`${data?.total || 0} contacts`}
        actions={
          <Button icon={Plus} onClick={() => setShowCreate(!showCreate)}>
            Add Contact
          </Button>
        }
      />

      {/* Create Form */}
      {showCreate && (
        <form className="contact-create-form" onSubmit={handleCreate}>
          <input placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Phone *" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} required />
          <input placeholder="Company" value={form.company} onChange={e => setForm({ ...form, company: e.target.value })} />
          <input placeholder="Source" value={form.source} onChange={e => setForm({ ...form, source: e.target.value })} />
          <Button type="submit" loading={creating}>Create</Button>
          <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
        </form>
      )}

      {/* Search */}
      <div className="contacts-search">
        <Search size={16} />
        <input placeholder="Search contacts..." value={search} onChange={e => setSearch(e.target.value)} />
      </div>

      {/* Table */}
      {contacts.length === 0 ? (
        <EmptyState icon={Users} title="No contacts" description="Add your first contact to get started." />
      ) : (
        <div className="contacts-table-wrap">
          <table className="contacts-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Company</th>
                <th>Stage</th>
                <th>Score</th>
                <th>Tags</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {contacts.map(c => (
                <tr key={c.contact_id} onClick={() => navigate(`/conversations/${c.contact_id}`)} className="contacts-row">
                  <td>
                    <div className="contact-cell-name">
                      <div className="contact-cell-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                      <span>{c.name || 'Unknown'}</span>
                    </div>
                  </td>
                  <td className="text-muted">{c.phone}</td>
                  <td className="text-muted">{c.company || '-'}</td>
                  <td>
                    <Badge variant={STAGE_VARIANTS[c.pipeline_stage] || 'default'}>
                      {c.pipeline_stage}
                    </Badge>
                  </td>
                  <td>{c.lead_score || 0}</td>
                  <td>
                    <div className="contact-tags">
                      {(c.tags || []).slice(0, 3).map(t => (
                        <Badge key={t} variant="gray" size="sm">{t}</Badge>
                      ))}
                    </div>
                  </td>
                  <td>
                    <button className="contact-delete" onClick={(e) => { e.stopPropagation(); handleDelete(c.contact_id, c.name); }}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
