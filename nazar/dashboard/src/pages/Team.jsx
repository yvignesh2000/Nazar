import { useState } from 'react';
import {
  Users as UsersIcon, UserPlus, Mail, Shield, Trash2,
  MoreHorizontal, X, Check, AlertCircle,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { users as usersApi, invites as invitesApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import './Team.css';

const ROLE_BADGES = {
  owner: 'orange',
  admin: 'primary',
  agent: 'success',
  viewer: 'gray',
};

export default function Team() {
  const { data, loading, refetch } = useApi(() => usersApi.list(), []);
  const { data: inviteData, refetch: refetchInvites } = useApi(() => invitesApi.list(), []);
  const [showInvite, setShowInvite] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [invEmail, setInvEmail] = useState('');
  const [invRole, setInvRole] = useState('agent');
  const [inviting, setInviting] = useState(false);
  const [addForm, setAddForm] = useState({ name: '', email: '', password: '', role: 'agent' });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');

  const usersList = data?.users || [];
  const invitesList = inviteData?.invites || [];
  const pendingInvites = invitesList.filter(i => i.status === 'pending');

  async function handleInvite(e) {
    e.preventDefault();
    if (!invEmail) return;
    setInviting(true);
    setError('');
    try {
      await invitesApi.create(invEmail, invRole);
      setInvEmail('');
      setShowInvite(false);
      refetchInvites();
    } catch (err) {
      setError(err?.message || 'Failed to send invite');
    } finally {
      setInviting(false);
    }
  }

  async function handleAddUser(e) {
    e.preventDefault();
    if (!addForm.email || !addForm.password) { setError('Email and password required'); return; }
    setAdding(true);
    setError('');
    try {
      await usersApi.create(addForm);
      setAddForm({ name: '', email: '', password: '', role: 'agent' });
      setShowAdd(false);
      refetch();
    } catch (err) {
      setError(err?.message || 'Failed to create user');
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(userId) {
    if (!confirm('Remove this user? This action cannot be undone.')) return;
    try {
      await usersApi.delete(userId);
      refetch();
    } catch (err) {
      alert('Delete failed: ' + (err?.message || 'Unknown error'));
    }
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Team"
        description="Manage users and roles"
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <Button icon={Mail} variant="secondary" onClick={() => { setShowInvite(true); setShowAdd(false); setError(''); }}>
              Invite
            </Button>
            <Button icon={UserPlus} onClick={() => { setShowAdd(true); setShowInvite(false); setError(''); }}>
              Add User
            </Button>
          </div>
        }
      />

      {error && (
        <div className="team-error">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}

      {/* Invite form */}
      {showInvite && (
        <div className="team-form-card">
          <div className="team-form-header">
            <h3>Invite Team Member</h3>
            <button className="team-form-close" onClick={() => setShowInvite(false)}><X size={18} /></button>
          </div>
          <form onSubmit={handleInvite} className="team-form">
            <div className="team-form-row">
              <input
                type="email"
                placeholder="email@company.com"
                value={invEmail}
                onChange={e => setInvEmail(e.target.value)}
                autoFocus
              />
              <select value={invRole} onChange={e => setInvRole(e.target.value)}>
                <option value="admin">Admin</option>
                <option value="agent">Agent</option>
                <option value="viewer">Viewer</option>
              </select>
              <Button icon={Mail} loading={inviting} type="submit">Send Invite</Button>
            </div>
          </form>
        </div>
      )}

      {/* Add user form */}
      {showAdd && (
        <div className="team-form-card">
          <div className="team-form-header">
            <h3>Add User Directly</h3>
            <button className="team-form-close" onClick={() => setShowAdd(false)}><X size={18} /></button>
          </div>
          <form onSubmit={handleAddUser} className="team-form">
            <div className="team-form-fields">
              <div className="team-form-field">
                <label>Name</label>
                <input
                  placeholder="Full name"
                  value={addForm.name}
                  onChange={e => setAddForm({ ...addForm, name: e.target.value })}
                />
              </div>
              <div className="team-form-field">
                <label>Email *</label>
                <input
                  type="email"
                  placeholder="email@company.com"
                  value={addForm.email}
                  onChange={e => setAddForm({ ...addForm, email: e.target.value })}
                  required
                />
              </div>
              <div className="team-form-field">
                <label>Password *</label>
                <input
                  type="password"
                  placeholder="Min 8 characters"
                  value={addForm.password}
                  onChange={e => setAddForm({ ...addForm, password: e.target.value })}
                  required
                />
              </div>
              <div className="team-form-field">
                <label>Role</label>
                <select value={addForm.role} onChange={e => setAddForm({ ...addForm, role: e.target.value })}>
                  <option value="admin">Admin</option>
                  <option value="agent">Agent</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>
            </div>
            <Button icon={UserPlus} loading={adding} type="submit">Create User</Button>
          </form>
        </div>
      )}

      {/* Users list */}
      <div className="team-table-wrap">
        <table className="team-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Status</th>
              <th>Added</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {usersList.map(u => (
              <tr key={u.user_id}>
                <td>
                  <div className="team-user-cell">
                    <div className="team-avatar">{(u.name || u.email || '?')[0].toUpperCase()}</div>
                    <div>
                      <span className="team-name">{u.name || '—'}</span>
                      <span className="team-email">{u.email}</span>
                    </div>
                  </div>
                </td>
                <td>
                  <Badge variant={ROLE_BADGES[u.role] || 'gray'}>{u.role}</Badge>
                </td>
                <td>
                  <Badge variant={u.status === 'active' ? 'success' : 'gray'} dot>{u.status || 'active'}</Badge>
                </td>
                <td className="team-date">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                </td>
                <td>
                  {u.role !== 'owner' && (
                    <button className="team-delete-btn" onClick={() => handleDelete(u.user_id)} title="Remove user">
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {usersList.length === 0 && (
              <tr>
                <td colSpan={5} className="team-empty">No users found</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pending invites */}
      {pendingInvites.length > 0 && (
        <div className="team-invites-section">
          <h3 className="team-section-title">Pending Invitations</h3>
          <div className="team-invites-list">
            {pendingInvites.map(inv => (
              <div key={inv.invite_id} className="team-invite-item">
                <Mail size={16} />
                <span className="team-invite-email">{inv.email}</span>
                <Badge variant={ROLE_BADGES[inv.role] || 'gray'}>{inv.role}</Badge>
                <span className="team-invite-date">
                  {inv.created_at ? new Date(inv.created_at).toLocaleDateString() : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
