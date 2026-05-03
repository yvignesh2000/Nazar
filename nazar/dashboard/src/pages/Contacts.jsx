import { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Users, Plus, Search, Trash2, Upload, Download, FileText, CheckCircle, AlertCircle, X,
  FolderOpen, UserPlus, ArrowLeft, UserMinus, ChevronDown, LayoutList, Columns,
  Brain, Lock, Edit2, Tag, DollarSign, Info,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { contacts as contactsApi, groups as groupsApi, pipeline as pipelineApi } from '../api/client';
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

const STAGE_COLORS = {
  New: '#6366f1', Qualified: '#8b5cf6', Proposal: '#f59e0b',
  Negotiation: '#f97316', Won: '#10b981', Lost: '#ef4444',
};

const PIPELINE_STAGES = ['New', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];

const SAMPLE_CSV = `name,phone,company,source,tags
Rahul Sharma,+919876543210,Acme Corp,website,interested;premium
Priya Patel,+919876543211,TechSoft,referral,demo-requested
John Doe,+14155551234,GlobalCo,linkedin,`;

/* ── CSV Import Modal ──────────────────────────────────────────── */
function ImportModal({ onClose, onImported }) {
  const [step, setStep] = useState('upload');
  const [csvText, setCsvText] = useState('');
  const [fileName, setFileName] = useState('');
  const [previewRows, setPreviewRows] = useState([]);
  const [previewHeaders, setPreviewHeaders] = useState([]);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);

  function parsePreview(text) {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return;
    const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
    const rows = lines.slice(1, 11).map(line => {
      const values = line.split(',');
      const row = {};
      headers.forEach((h, i) => { row[h] = (values[i] || '').trim(); });
      return row;
    });
    setPreviewHeaders(headers);
    setPreviewRows(rows);
    setCsvText(text);
    setStep('preview');
  }

  function handleFileSelect(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) { alert('Please select a .csv file'); return; }
    if (file.size > 5 * 1024 * 1024) { alert('File too large (max 5MB)'); return; }
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => parsePreview(e.target.result);
    reader.readAsText(file);
  }

  function handleDrop(e) { e.preventDefault(); setDragOver(false); handleFileSelect(e.dataTransfer.files?.[0]); }

  async function handleImport() {
    if (!csvText) return;
    setImporting(true);
    try {
      const res = await contactsApi.import(csvText);
      setResult(res);
      setStep('result');
      if (res.created > 0) onImported();
    } catch (err) {
      setResult({ created: 0, skipped: 0, errors: [err.message || 'Import failed'] });
      setStep('result');
    } finally { setImporting(false); }
  }

  function downloadSample() {
    const blob = new Blob([SAMPLE_CSV], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'nazar_contacts_sample.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  const hasRequiredHeaders = previewHeaders.includes('name') && previewHeaders.includes('phone');
  const totalLines = csvText ? csvText.trim().split('\n').length - 1 : 0;

  return (
    <div className="import-overlay" onClick={onClose}>
      <div className="import-modal" onClick={e => e.stopPropagation()}>
        <div className="import-header">
          <h2><Upload size={20} /> Import Contacts</h2>
          <button className="import-close" onClick={onClose}><X size={18} /></button>
        </div>

        {step === 'upload' && (
          <div className="import-body">
            <div className={`import-dropzone ${dragOver ? 'import-dropzone--active' : ''}`} onDrop={handleDrop} onDragOver={e => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onClick={() => fileRef.current?.click()}>
              <FileText size={36} />
              <p className="import-dropzone-title">Drop a CSV file here or click to browse</p>
              <p className="import-dropzone-hint">Required columns: <strong>name</strong>, <strong>phone</strong></p>
              <p className="import-dropzone-hint">Optional: company, source, tags (semicolon-separated)</p>
              <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={e => handleFileSelect(e.target.files?.[0])} />
            </div>
            <div className="import-or"><span>or paste CSV content</span></div>
            <textarea className="import-paste" placeholder={`name,phone,company\nRahul Sharma,+919876543210,Acme Corp`} rows={6} value={csvText} onChange={e => setCsvText(e.target.value)} />
            <div className="import-actions">
              <Button variant="ghost" icon={Download} onClick={downloadSample} size="sm">Download Sample CSV</Button>
              <Button onClick={() => csvText.trim() && parsePreview(csvText)} disabled={!csvText.trim()}>Preview Import</Button>
            </div>
          </div>
        )}

        {step === 'preview' && (
          <div className="import-body">
            <div className="import-preview-info">
              {fileName && <Badge variant="default" size="sm"><FileText size={12} /> {fileName}</Badge>}
              <span className="import-row-count">{totalLines} row{totalLines !== 1 ? 's' : ''} found</span>
              {hasRequiredHeaders ? <Badge variant="success" size="sm"><CheckCircle size={12} /> Headers valid</Badge> : <Badge variant="danger" size="sm"><AlertCircle size={12} /> Missing required headers (name, phone)</Badge>}
            </div>
            <div className="import-preview-table-wrap">
              <table className="import-preview-table">
                <thead><tr><th>#</th>{previewHeaders.map(h => <th key={h} className={['name','phone'].includes(h) ? 'import-required-col' : ''}>{h}{['name','phone'].includes(h) && <span className="import-req-star">*</span>}</th>)}</tr></thead>
                <tbody>{previewRows.map((row, i) => <tr key={i}><td className="import-row-num">{i+1}</td>{previewHeaders.map(h => <td key={h}>{row[h] || <span className="import-empty">—</span>}</td>)}</tr>)}</tbody>
              </table>
            </div>
            {totalLines > 10 && <p className="import-preview-more">Showing first 10 of {totalLines} rows</p>}
            <div className="import-actions">
              <Button variant="ghost" onClick={() => { setStep('upload'); setPreviewRows([]); setPreviewHeaders([]); }}>Back</Button>
              <Button icon={Upload} onClick={handleImport} loading={importing} disabled={!hasRequiredHeaders}>Import {totalLines} Contact{totalLines !== 1 ? 's' : ''}</Button>
            </div>
          </div>
        )}

        {step === 'result' && result && (
          <div className="import-body">
            <div className="import-result">
              <div className={`import-result-icon ${result.created > 0 ? 'import-result-icon--success' : 'import-result-icon--warning'}`}>
                {result.created > 0 ? <CheckCircle size={40} /> : <AlertCircle size={40} />}
              </div>
              <h3 className="import-result-title">{result.created > 0 ? 'Import Complete!' : 'Import Finished'}</h3>
              <div className="import-result-stats">
                <div className="import-stat import-stat--created"><span className="import-stat-num">{result.created}</span><span className="import-stat-label">Created</span></div>
                <div className="import-stat import-stat--skipped"><span className="import-stat-num">{result.skipped}</span><span className="import-stat-label">Skipped</span></div>
                <div className="import-stat import-stat--errors"><span className="import-stat-num">{result.errors?.length || 0}</span><span className="import-stat-label">Errors</span></div>
              </div>
              {result.errors && result.errors.length > 0 && (
                <div className="import-errors"><strong>Errors:</strong><ul>{result.errors.slice(0, 10).map((err, i) => <li key={i}>{err}</li>)}</ul></div>
              )}
            </div>
            <div className="import-actions">
              <Button variant="ghost" onClick={() => { setStep('upload'); setCsvText(''); setResult(null); setFileName(''); }}>Import More</Button>
              <Button onClick={onClose}>Done</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Add Members Modal ─────────────────────────────────────────── */
function AddMembersModal({ group, allContacts, existingMemberIds, onClose, onAdded }) {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(new Set());
  const [adding, setAdding] = useState(false);

  const available = allContacts.filter(c =>
    !existingMemberIds.has(c.contact_id) && (!search || (c.name || '').toLowerCase().includes(search.toLowerCase()) || (c.phone || '').includes(search))
  );

  function toggleContact(id) { setSelected(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; }); }
  function toggleAll() { setSelected(selected.size === available.length ? new Set() : new Set(available.map(c => c.contact_id))); }

  async function handleAdd() {
    if (selected.size === 0) return;
    setAdding(true);
    try { await groupsApi.addMembers(group.id, [...selected]); onAdded(); onClose(); }
    catch (err) { alert(err.message || 'Failed to add members'); }
    finally { setAdding(false); }
  }

  return (
    <div className="import-overlay" onClick={onClose}>
      <div className="import-modal add-members-modal" onClick={e => e.stopPropagation()}>
        <div className="import-header">
          <h2><UserPlus size={20} /> Add contacts to <span style={{ color: group.color || '#6366f1' }}>{group.name}</span></h2>
          <button className="import-close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="import-body">
          <div className="contacts-search" style={{ margin: '0 0 var(--space-3) 0' }}>
            <Search size={16} /><input placeholder="Search contacts to add..." value={search} onChange={e => setSearch(e.target.value)} autoFocus />
          </div>
          {available.length === 0 ? (
            <div className="add-members-empty">{allContacts.length === existingMemberIds.size ? 'All contacts are already in this group.' : 'No contacts match your search.'}</div>
          ) : (
            <>
              <div className="add-members-select-all">
                <label className="add-members-checkbox-label"><input type="checkbox" checked={selected.size === available.length && available.length > 0} onChange={toggleAll} /> Select all ({available.length})</label>
                {selected.size > 0 && <Badge variant="primary" size="sm">{selected.size} selected</Badge>}
              </div>
              <div className="add-members-list">
                {available.map(c => (
                  <label key={c.contact_id} className={`add-members-row ${selected.has(c.contact_id) ? 'add-members-row--selected' : ''}`}>
                    <input type="checkbox" checked={selected.has(c.contact_id)} onChange={() => toggleContact(c.contact_id)} />
                    <div className="contact-cell-avatar">{(c.name || '?')[0].toUpperCase()}</div>
                    <div className="add-members-row-info">
                      <span className="add-members-row-name">{c.name || 'Unknown'}</span>
                      <span className="add-members-row-phone">{c.phone}{c.company ? ` · ${c.company}` : ''}</span>
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}
          <div className="import-actions">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button icon={UserPlus} onClick={handleAdd} loading={adding} disabled={selected.size === 0}>Add {selected.size || ''} Contact{selected.size !== 1 ? 's' : ''}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Contact Detail Drawer ─────────────────────────────────────── */
function ContactDrawer({ contact, onClose, onUpdated }) {
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: contact.name || '',
    company: contact.company || '',
    pipeline_stage: contact.pipeline_stage || 'New',
    deal_value: contact.deal_value || 0,
    tags: (contact.tags || []).join(', '),
  });
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      const tagsArray = form.tags.split(',').map(t => t.trim()).filter(Boolean);
      await contactsApi.update(contact.contact_id, {
        name: form.name,
        company: form.company,
        pipeline_stage: form.pipeline_stage,
        deal_value: Number(form.deal_value) || 0,
        tags: tagsArray,
      });
      setEditing(false);
      onUpdated();
    } catch (err) {
      alert(err.message || 'Failed to update');
    } finally { setSaving(false); }
  }

  return (
    <div className="contact-drawer-overlay" onClick={onClose}>
      <div className="contact-drawer" onClick={e => e.stopPropagation()}>
        <div className="contact-drawer-header">
          <div className="contact-drawer-avatar">{(contact.name || '?')[0].toUpperCase()}</div>
          <div>
            <h3>{contact.name || 'Unknown'}</h3>
            <span className="contact-drawer-phone">{contact.phone}</span>
          </div>
          <button className="import-close" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="contact-drawer-body">
          {!editing ? (
            <>
              <div className="drawer-field">
                <span className="drawer-field-label">Status</span>
                <Badge variant={STAGE_VARIANTS[contact.pipeline_stage] || 'default'}>{contact.pipeline_stage || 'New'}</Badge>
              </div>
              <div className="drawer-field">
                <span className="drawer-field-label">Company</span>
                <span>{contact.company || '—'}</span>
              </div>
              <div className="drawer-field">
                <span className="drawer-field-label">Deal Value</span>
                <span>{contact.deal_value ? `₹${contact.deal_value.toLocaleString('en-IN')}` : '—'}</span>
              </div>
              <div className="drawer-field">
                <span className="drawer-field-label">Lead Score</span>
                <span title="How likely this contact is to convert (0-100)">{contact.lead_score || 0} / 100</span>
              </div>
              <div className="drawer-field">
                <span className="drawer-field-label">Source</span>
                <span>{contact.source || '—'}</span>
              </div>
              <div className="drawer-field">
                <span className="drawer-field-label">Tags</span>
                <div className="contact-tags">
                  {(contact.tags || []).length > 0 ? (contact.tags || []).map(t => <Badge key={t} variant="gray" size="sm">{t}</Badge>) : <span className="text-muted">No tags</span>}
                </div>
              </div>
              <div className="drawer-actions">
                <Button size="sm" icon={Edit2} onClick={() => setEditing(true)}>Edit</Button>
                <Button size="sm" variant="secondary" onClick={() => navigate(`/inbox/${contact.contact_id}`)}>Open Chat</Button>
              </div>
            </>
          ) : (
            <>
              <div className="drawer-edit-field"><label>Name</label><input value={form.name} onChange={e => setForm({...form, name: e.target.value})} /></div>
              <div className="drawer-edit-field"><label>Company</label><input value={form.company} onChange={e => setForm({...form, company: e.target.value})} /></div>
              <div className="drawer-edit-field">
                <label>Status</label>
                <select value={form.pipeline_stage} onChange={e => setForm({...form, pipeline_stage: e.target.value})}>
                  {PIPELINE_STAGES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="drawer-edit-field"><label>Deal Value (₹)</label><input type="number" value={form.deal_value} onChange={e => setForm({...form, deal_value: e.target.value})} /></div>
              <div className="drawer-edit-field"><label>Tags (comma separated)</label><input value={form.tags} onChange={e => setForm({...form, tags: e.target.value})} placeholder="vip, interested, demo" /></div>
              <div className="drawer-actions">
                <Button size="sm" onClick={handleSave} loading={saving}>Save</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Group Detail View ────────────────────────────────────────── */
function GroupDetail({ group, allContacts, onBack, onGroupUpdated }) {
  const [members, setMembers] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [removing, setRemoving] = useState(null);

  async function loadMembers() {
    setLoadingMembers(true);
    try { const res = await groupsApi.get(group.id); setMembers(res.members || []); }
    catch { setMembers([]); }
    finally { setLoadingMembers(false); }
  }

  useEffect(() => { loadMembers(); }, [group.id]);

  async function handleRemove(contactId, contactName) {
    if (!confirm(`Remove "${contactName}" from "${group.name}"?`)) return;
    setRemoving(contactId);
    try { await groupsApi.removeMembers(group.id, [contactId]); setMembers(prev => prev.filter(m => (m.contact_id || m.id) !== contactId)); onGroupUpdated(); }
    catch (err) { alert(err.message || 'Failed to remove'); }
    finally { setRemoving(null); }
  }

  const memberIds = new Set(members.map(m => m.contact_id || m.id));

  return (
    <div>
      <div className="group-detail-header">
        <button className="group-detail-back" onClick={onBack}><ArrowLeft size={16} /> All Groups</button>
        <div className="group-detail-title">
          <div className="group-card-dot" style={{ background: group.color || '#6366f1' }} />
          <h3>{group.name}</h3>
          <Badge variant="default" size="sm">{members.length} member{members.length !== 1 ? 's' : ''}</Badge>
        </div>
        {group.description && <p className="group-detail-desc">{group.description}</p>}
      </div>
      <div className="group-detail-actions">
        <Button size="sm" icon={UserPlus} onClick={() => setShowAddModal(true)}>Add Contacts</Button>
      </div>
      {loadingMembers ? <Spinner /> : members.length === 0 ? (
        <EmptyState icon={Users} title="No members yet" description="Add contacts to this group to use it in campaigns." action={<Button icon={UserPlus} onClick={() => setShowAddModal(true)}>Add Contacts</Button>} />
      ) : (
        <div className="contacts-table-wrap"><table className="contacts-table"><thead><tr><th>Name</th><th>Phone</th><th>Company</th><th>Tags</th><th></th></tr></thead><tbody>
          {members.map(m => { const id = m.contact_id || m.id; return (
            <tr key={id} className="contacts-row">
              <td><div className="contact-cell-name"><div className="contact-cell-avatar">{(m.name || '?')[0].toUpperCase()}</div><span>{m.name || 'Unknown'}</span></div></td>
              <td className="text-muted">{m.phone}</td><td className="text-muted">{m.company || '-'}</td>
              <td><div className="contact-tags">{(typeof m.tags === 'string' ? JSON.parse(m.tags || '[]') : (m.tags || [])).slice(0, 3).map(t => <Badge key={t} variant="gray" size="sm">{t}</Badge>)}</div></td>
              <td><button className="contact-delete" title="Remove from group" disabled={removing === id} onClick={() => handleRemove(id, m.name)}><UserMinus size={14} /></button></td>
            </tr>); })}
        </tbody></table></div>
      )}
      {showAddModal && <AddMembersModal group={group} allContacts={allContacts} existingMemberIds={memberIds} onClose={() => setShowAddModal(false)} onAdded={() => { loadMembers(); onGroupUpdated(); }} />}
    </div>
  );
}

/* ── Groups Panel ──────────────────────────────────────────────── */
const GROUP_COLORS = ['#6366f1', '#8b5cf6', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#ec4899', '#14b8a6'];

function GroupsPanel({ allContacts }) {
  const { data, loading, refetch } = useApi(() => groupsApi.list(), []);
  const [showCreate, setShowCreate] = useState(false);
  const [activeGroup, setActiveGroup] = useState(null);
  const [name, setName] = useState('');
  const [color, setColor] = useState(GROUP_COLORS[0]);
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);

  const groups = data?.groups || [];

  async function handleCreate(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try { await groupsApi.create({ name: name.trim(), color, description: description.trim() }); setShowCreate(false); setName(''); setDescription(''); refetch(); }
    catch (err) { alert(err.message || 'Failed to create group'); }
    finally { setCreating(false); }
  }

  async function handleDelete(e, id, gName) {
    e.stopPropagation();
    if (!confirm(`Delete group "${gName}"? Contacts won't be deleted.`)) return;
    await groupsApi.delete(id);
    if (activeGroup?.id === id) setActiveGroup(null);
    refetch();
  }

  if (loading) return <Spinner />;

  if (activeGroup) {
    return <GroupDetail group={activeGroup} allContacts={allContacts} onBack={() => { setActiveGroup(null); refetch(); }} onGroupUpdated={refetch} />;
  }

  return (
    <div>
      {/* How groups work */}
      <div className="groups-education">
        <Info size={14} />
        <span>Groups let you organize contacts for campaigns — like "VIP Customers," "Trial Users," or "Event Attendees."</span>
      </div>

      <div className="groups-header">
        <span className="groups-count">{groups.length} group{groups.length !== 1 ? 's' : ''}</span>
        <Button size="sm" icon={Plus} onClick={() => setShowCreate(true)}>New Group</Button>
      </div>

      {showCreate && (
        <form className="group-create-form" onSubmit={handleCreate}>
          <input placeholder="Group name *" value={name} onChange={e => setName(e.target.value)} required />
          <input placeholder="Description" value={description} onChange={e => setDescription(e.target.value)} />
          <div className="group-color-picker">{GROUP_COLORS.map(c => <button key={c} type="button" className={`group-color-dot ${color === c ? 'group-color-dot--active' : ''}`} style={{ background: c }} onClick={() => setColor(c)} />)}</div>
          <Button type="submit" size="sm" loading={creating}>Create</Button>
          <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>Cancel</Button>
        </form>
      )}

      {groups.length === 0 ? (
        <EmptyState icon={FolderOpen} title="No groups" description="Create groups to organize contacts for campaigns." />
      ) : (
        <div className="groups-grid">
          {groups.map(g => (
            <div key={g.id} className="group-card group-card--clickable" onClick={() => setActiveGroup(g)}>
              <div className="group-card-dot" style={{ background: g.color || '#6366f1' }} />
              <div className="group-card-info">
                <span className="group-card-name">{g.name}</span>
                <span className="group-card-count">{g.member_count || 0} contacts</span>
                {g.description && <span className="group-card-desc">{g.description}</span>}
              </div>
              <button className="contact-delete" onClick={(e) => handleDelete(e, g.id, g.name)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Pipeline Kanban View ─────────────────────────────────────── */
function PipelineView({ contacts, onRefetch }) {
  const navigate = useNavigate();
  const [draggedContact, setDraggedContact] = useState(null);
  const [dragOverStage, setDragOverStage] = useState(null);
  const [movingId, setMovingId] = useState(null);

  const stageMap = {};
  PIPELINE_STAGES.forEach(s => { stageMap[s] = []; });
  contacts.forEach(c => {
    const stage = c.pipeline_stage || 'New';
    if (stageMap[stage]) stageMap[stage].push(c);
    else stageMap.New.push(c);
  });

  function handleDragStart(e, contact, fromStage) {
    setDraggedContact({ ...contact, fromStage });
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', contact.contact_id);
  }

  async function handleDrop(e, toStage) {
    e.preventDefault();
    setDragOverStage(null);
    if (!draggedContact || draggedContact.fromStage === toStage) { setDraggedContact(null); return; }
    setMovingId(draggedContact.contact_id);
    try { await pipelineApi.moveStage(draggedContact.contact_id, toStage); onRefetch(); }
    catch (err) { console.error('Move failed:', err); }
    finally { setMovingId(null); setDraggedContact(null); }
  }

  return (
    <div>
      <div className="pipeline-hint">
        <Brain size={14} />
        <span>AI automatically moves contacts based on conversation context. Drag a card to manually override.</span>
      </div>

      <div className="pipeline-board">
        {PIPELINE_STAGES.map(stage => (
          <div key={stage} className={`pipeline-column ${dragOverStage === stage ? 'pipeline-column--dragover' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragOverStage(stage); }}
            onDragLeave={() => setDragOverStage(null)}
            onDrop={e => handleDrop(e, stage)}
          >
            <div className="pipeline-column-header">
              <div className="pipeline-stage-dot" style={{ background: STAGE_COLORS[stage] || '#6b7280' }} />
              <span className="pipeline-stage-name">{stage}</span>
              <span className="pipeline-stage-count">{stageMap[stage].length}</span>
            </div>
            <div className="pipeline-column-body">
              {stageMap[stage].map(c => (
                <div key={c.contact_id} className={`pipeline-card ${movingId === c.contact_id ? 'pipeline-card--moving' : ''}`}
                  draggable onDragStart={e => handleDragStart(e, c, stage)} onDragEnd={() => { setDraggedContact(null); setDragOverStage(null); }}
                  onClick={() => navigate(`/inbox/${c.contact_id}`)}
                >
                  <div className="pipeline-card-top">
                    <div className="pipeline-card-name">{c.name || 'Unknown'}</div>
                    {c.manual_stage_override ? (
                      <span className="pipeline-lock-icon" title="Manually set"><Lock size={11} /></span>
                    ) : (
                      <span className="pipeline-ai-badge" title="AI auto-classified"><Brain size={11} /></span>
                    )}
                  </div>
                  {c.company && <div className="pipeline-card-company">{c.company}</div>}
                  <div className="pipeline-card-footer">
                    {c.deal_value > 0 && <Badge variant="success" size="sm">₹{c.deal_value.toLocaleString('en-IN')}</Badge>}
                    {c.lead_score > 0 && <Badge variant="default" size="sm">{c.lead_score}</Badge>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main Contacts Page ────────────────────────────────────────── */
export default function Contacts() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialView = searchParams.get('view') === 'pipeline' ? 'pipeline' : 'table';

  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('contacts');
  const [view, setView] = useState(initialView);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [form, setForm] = useState({ name: '', phone: '', company: '', source: '', pipeline_stage: 'New', tags: '' });
  const [creating, setCreating] = useState(false);
  const [selectedContacts, setSelectedContacts] = useState(new Set());
  const [showGroupDropdown, setShowGroupDropdown] = useState(false);
  const [addingToGroup, setAddingToGroup] = useState(null);
  const [drawerContact, setDrawerContact] = useState(null);

  const { data, loading, refetch } = useApi(() => contactsApi.list(), []);
  const { data: groupsData, refetch: refetchGroups } = useApi(() => groupsApi.list(), []);
  const allContacts = data?.contacts || [];
  const availableGroups = groupsData?.groups || [];
  const contacts = allContacts.filter(c =>
    !search || (c.name || '').toLowerCase().includes(search.toLowerCase()) || (c.phone || '').includes(search) || (c.company || '').toLowerCase().includes(search.toLowerCase())
  );

  function toggleContactSelect(id) { setSelectedContacts(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; }); }
  function toggleSelectAll() { setSelectedContacts(selectedContacts.size === contacts.length ? new Set() : new Set(contacts.map(c => c.contact_id))); }

  async function addSelectedToGroup(groupId) {
    if (selectedContacts.size === 0) return;
    setAddingToGroup(groupId);
    try { await groupsApi.addMembers(groupId, [...selectedContacts]); setSelectedContacts(new Set()); setShowGroupDropdown(false); refetchGroups(); }
    catch (err) { alert(err.message || 'Failed to add to group'); }
    finally { setAddingToGroup(null); }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!form.phone) return;
    setCreating(true);
    try {
      const tagsArray = form.tags ? form.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
      await contactsApi.create({ ...form, tags: tagsArray });
      setShowCreate(false);
      setForm({ name: '', phone: '', company: '', source: '', pipeline_stage: 'New', tags: '' });
      refetch();
    } catch (err) { alert(err.message); }
    finally { setCreating(false); }
  }

  async function handleDelete(id, name) {
    if (!confirm(`Delete ${name || 'this contact'}?`)) return;
    await contactsApi.delete(id);
    refetch();
  }

  function handleRowClick(e, contact) {
    // Open drawer instead of navigating to conversation
    setDrawerContact(contact);
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Contacts"
        description={`${data?.total || 0} contact${(data?.total || 0) === 1 ? '' : 's'}`}
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <Button variant="secondary" icon={Upload} onClick={() => setShowImport(true)}>Import CSV</Button>
            <Button icon={Plus} onClick={() => setShowCreate(!showCreate)}>Add Contact</Button>
          </div>
        }
      />

      {/* Tabs */}
      <div className="contacts-tabs">
        <button className={`tab ${tab === 'contacts' ? 'tab--active' : ''}`} onClick={() => setTab('contacts')}>
          <Users size={15} /> Contacts
        </button>
        <button className={`tab ${tab === 'groups' ? 'tab--active' : ''}`} onClick={() => setTab('groups')}>
          <FolderOpen size={15} /> Groups
        </button>

        {/* View toggle (only in contacts tab) */}
        {tab === 'contacts' && (
          <div className="view-toggle">
            <button className={`view-toggle-btn ${view === 'table' ? 'view-toggle-btn--active' : ''}`} onClick={() => setView('table')} title="Table view"><LayoutList size={16} /></button>
            <button className={`view-toggle-btn ${view === 'pipeline' ? 'view-toggle-btn--active' : ''}`} onClick={() => setView('pipeline')} title="Pipeline view"><Columns size={16} /></button>
          </div>
        )}
      </div>

      {/* Groups tab */}
      {tab === 'groups' && <GroupsPanel allContacts={allContacts} />}

      {/* Create form — structured card layout */}
      {tab === 'contacts' && showCreate && (
        <form className="contact-create-form" onSubmit={handleCreate}>
          <div className="contact-form-title">
            <UserPlus size={18} />
            <span>New Contact</span>
          </div>
          <div className="contact-form-grid">
            <div className="contact-form-field">
              <label className="contact-form-label">Name</label>
              <input placeholder="e.g. Rahul Sharma" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="contact-form-field contact-form-field--required">
              <label className="contact-form-label">Phone <span className="contact-form-req">*</span></label>
              <input placeholder="e.g. +919876543210" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} required />
            </div>
            <div className="contact-form-field">
              <label className="contact-form-label">Company</label>
              <input placeholder="e.g. Acme Corp" value={form.company} onChange={e => setForm({ ...form, company: e.target.value })} />
            </div>
            <div className="contact-form-field">
              <label className="contact-form-label">Source</label>
              <input placeholder="e.g. Website, Referral" value={form.source} onChange={e => setForm({ ...form, source: e.target.value })} />
            </div>
            <div className="contact-form-field">
              <label className="contact-form-label">Status</label>
              <select value={form.pipeline_stage} onChange={e => setForm({ ...form, pipeline_stage: e.target.value })}>
                {PIPELINE_STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="contact-form-field">
              <label className="contact-form-label">Tags</label>
              <input placeholder="e.g. vip, interested, demo" value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} />
            </div>
          </div>
          <div className="contact-form-actions">
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button type="submit" icon={Plus} loading={creating}>Create Contact</Button>
          </div>
        </form>
      )}

      {/* Pipeline Kanban View */}
      {tab === 'contacts' && view === 'pipeline' && (
        <PipelineView contacts={allContacts} onRefetch={refetch} />
      )}

      {/* Table View */}
      {tab === 'contacts' && view === 'table' && (
        <>
          <div className="contacts-search">
            <Search size={16} />
            <input placeholder="Search contacts..." value={search} onChange={e => setSearch(e.target.value)} />
          </div>

          {selectedContacts.size > 0 && (
            <div className="bulk-action-bar">
              <span className="bulk-action-count">{selectedContacts.size} selected</span>
              <div className="bulk-action-group-wrap">
                <Button size="sm" variant="secondary" icon={FolderOpen} onClick={() => setShowGroupDropdown(!showGroupDropdown)}>
                  Add to Group <ChevronDown size={12} />
                </Button>
                {showGroupDropdown && (
                  <div className="bulk-group-dropdown">
                    {availableGroups.length === 0 ? (
                      <div className="bulk-group-empty">No groups yet. <button onClick={() => { setShowGroupDropdown(false); setTab('groups'); }}>Create one</button></div>
                    ) : availableGroups.map(g => (
                      <button key={g.id} className="bulk-group-option" disabled={addingToGroup === g.id} onClick={() => addSelectedToGroup(g.id)}>
                        <span className="group-card-dot" style={{ background: g.color || '#6366f1' }} /><span>{g.name}</span><span className="bulk-group-count">{g.member_count || 0}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Button size="sm" variant="ghost" onClick={() => setSelectedContacts(new Set())}>Clear</Button>
            </div>
          )}

          {contacts.length === 0 ? (
            <EmptyState
              icon={Users} title="No contacts"
              description="Add your first contact or import a CSV to get started."
              action={<div style={{ display: 'flex', gap: '8px' }}><Button variant="secondary" icon={Upload} onClick={() => setShowImport(true)}>Import CSV</Button><Button icon={Plus} onClick={() => setShowCreate(true)}>Add Contact</Button></div>}
            />
          ) : (
            <div className="contacts-table-wrap">
              <table className="contacts-table">
                <thead><tr>
                  <th className="contacts-th-check"><input type="checkbox" checked={selectedContacts.size === contacts.length && contacts.length > 0} onChange={toggleSelectAll} /></th>
                  <th>Name</th><th>Phone</th><th>Company</th><th>Status</th><th>Score</th><th>Tags</th><th></th>
                </tr></thead>
                <tbody>
                  {contacts.map(c => (
                    <tr key={c.contact_id} className={`contacts-row ${selectedContacts.has(c.contact_id) ? 'contacts-row--selected' : ''}`} onClick={(e) => handleRowClick(e, c)}>
                      <td className="contacts-td-check" onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={selectedContacts.has(c.contact_id)} onChange={() => toggleContactSelect(c.contact_id)} />
                      </td>
                      <td><div className="contact-cell-name"><div className="contact-cell-avatar">{(c.name || '?')[0].toUpperCase()}</div><span>{c.name || 'Unknown'}</span></div></td>
                      <td className="text-muted">{c.phone}</td>
                      <td className="text-muted">{c.company || '-'}</td>
                      <td><Badge variant={STAGE_VARIANTS[c.pipeline_stage] || 'default'}>{c.pipeline_stage}</Badge></td>
                      <td><span title="How likely this contact is to convert (0-100)">{c.lead_score || 0}</span></td>
                      <td><div className="contact-tags">{(c.tags || []).slice(0, 3).map(t => <Badge key={t} variant="gray" size="sm">{t}</Badge>)}</div></td>
                      <td><button className="contact-delete" onClick={(e) => { e.stopPropagation(); handleDelete(c.contact_id, c.name); }}><Trash2 size={14} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Contact Detail Drawer */}
      {drawerContact && <ContactDrawer contact={drawerContact} onClose={() => setDrawerContact(null)} onUpdated={() => { refetch(); setDrawerContact(null); }} />}

      {/* Import Modal */}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImported={refetch} />}
    </div>
  );
}
