import { useState, useMemo } from 'react';
import { FileText, Plus, Trash2, Edit, Search, Filter, Eye, X, ChevronDown, Variable, Bold, Italic, Smile, CheckCircle, Clock, XCircle, BarChart3, Send, Image, Video, FileDown, MapPin, Type, CornerDownRight } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { templates as templateApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import StatCard from '../components/ui/StatCard';
import './Templates.css';

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'Hindi' },
  { code: 'ta', label: 'Tamil' },
  { code: 'te', label: 'Telugu' },
  { code: 'kn', label: 'Kannada' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'mr', label: 'Marathi' },
  { code: 'gu', label: 'Gujarati' },
  { code: 'bn', label: 'Bengali' },
  { code: 'pt_BR', label: 'Portuguese (BR)' },
  { code: 'es', label: 'Spanish' },
  { code: 'ar', label: 'Arabic' },
];

const STATUS_MAP = {
  approved: { variant: 'success', icon: CheckCircle, label: 'Approved' },
  pending:  { variant: 'warning', icon: Clock,       label: 'Pending' },
  rejected: { variant: 'danger',  icon: XCircle,     label: 'Rejected' },
};

const HEADER_ICONS = {
  none: null,
  text: Type,
  image: Image,
  video: Video,
  document: FileDown,
};

const VARIABLE_PRESETS = [
  { name: 'name', label: 'Customer Name', example: 'John' },
  { name: 'company', label: 'Company', example: 'Acme Corp' },
  { name: 'phone', label: 'Phone', example: '+919876543210' },
  { name: 'topic', label: 'Topic', example: 'our discussion' },
  { name: 'deal_value', label: 'Deal Value', example: '₹50,000' },
  { name: 'stage', label: 'Pipeline Stage', example: 'Qualified' },
];

// ─── WhatsApp Phone Preview ───────────────────────────────────────
function WhatsAppPreview({ header, body, footer, buttons }) {
  const previewBody = body || 'Your message body will appear here...';

  return (
    <div className="wa-preview">
      <div className="wa-preview-label">Preview</div>
      <div className="wa-phone">
        <div className="wa-phone-notch" />
        <div className="wa-phone-header">
          <div className="wa-phone-avatar">N</div>
          <div className="wa-phone-name">
            <span>Nazar Business</span>
            <span className="wa-phone-status">online</span>
          </div>
        </div>
        <div className="wa-phone-chat">
          <div className="wa-bubble">
            {header && header.type !== 'none' && (
              <div className="wa-bubble-header">
                {header.type === 'text' && <strong>{header.text || 'Header text'}</strong>}
                {header.type === 'image' && <div className="wa-media-placeholder"><Image size={32} /><span>Image</span></div>}
                {header.type === 'video' && <div className="wa-media-placeholder"><Video size={32} /><span>Video</span></div>}
                {header.type === 'document' && <div className="wa-media-placeholder"><FileDown size={32} /><span>Document</span></div>}
              </div>
            )}
            <div className="wa-bubble-body">{previewBody}</div>
            {footer && <div className="wa-bubble-footer">{footer}</div>}
            {buttons && buttons.length > 0 && (
              <div className="wa-bubble-buttons">
                {buttons.map((btn, i) => (
                  <div key={i} className="wa-bubble-btn">{btn.text || `Button ${i + 1}`}</div>
                ))}
              </div>
            )}
            <div className="wa-bubble-time">now</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Template Builder Modal ───────────────────────────────────────
function TemplateBuilder({ template, onSave, onClose, saving }) {
  const isEdit = !!template;
  const [form, setForm] = useState({
    name: template?.name || '',
    category: template?.category || 'utility',
    language: template?.language || 'en',
    description: template?.description || '',
    header: template?.header || { type: 'none' },
    body: template?.body || '',
    footer: template?.footer || '',
    buttons: template?.buttons || [],
    variables: template?.variables || [],
  });

  function insertVariable() {
    const nextNum = (form.body.match(/\{\{\d+\}\}/g) || []).length + 1;
    setForm(f => ({ ...f, body: f.body + `{{${nextNum}}}` }));
  }

  function addButton(type) {
    if (form.buttons.length >= 3) return;
    const btn = type === 'quick_reply'
      ? { type: 'quick_reply', text: '' }
      : type === 'url'
        ? { type: 'url', text: '', url: '' }
        : { type: 'phone', text: '', phone: '' };
    setForm(f => ({ ...f, buttons: [...f.buttons, btn] }));
  }

  function updateButton(idx, field, value) {
    setForm(f => {
      const btns = [...f.buttons];
      btns[idx] = { ...btns[idx], [field]: value };
      return { ...f, buttons: btns };
    });
  }

  function removeButton(idx) {
    setForm(f => ({ ...f, buttons: f.buttons.filter((_, i) => i !== idx) }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (!form.name || !form.body) return;

    // Auto-detect variables from body
    const varMatches = form.body.match(/\{\{(\d+)\}\}/g) || [];
    const varNames = varMatches.map((_, i) => VARIABLE_PRESETS[i]?.name || `var${i + 1}`);

    onSave({
      ...form,
      variables: varNames,
    });
  }

  return (
    <div className="template-builder-overlay">
      <div className="template-builder">
        <div className="template-builder-header">
          <h2>{isEdit ? 'Edit Template' : 'Create Template'}</h2>
          <div className="template-builder-header-actions">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={handleSubmit} loading={saving} icon={isEdit ? Edit : Plus}>
              {isEdit ? 'Update' : 'Submit for Approval'}
            </Button>
          </div>
        </div>

        <div className="template-builder-content">
          {/* Left: Form */}
          <div className="template-builder-form">
            {/* Meta Fields */}
            <div className="tb-field">
              <label>Template Name *<span className="tb-field-hint">{form.name.length}/60</span></label>
              <input
                placeholder="welcome_template, order_confirmation..."
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 60) })}
                maxLength={60}
                required
                disabled={isEdit}
              />
            </div>

            <div className="tb-row-3">
              <div className="tb-field">
                <label>Category *</label>
                <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
                  <option value="utility">Utility</option>
                  <option value="marketing">Marketing</option>
                  <option value="authentication">Authentication</option>
                </select>
              </div>
              <div className="tb-field">
                <label>Language *</label>
                <select value={form.language} onChange={e => setForm({ ...form, language: e.target.value })}>
                  {LANGUAGES.map(l => (
                    <option key={l.code} value={l.code}>{l.label}</option>
                  ))}
                </select>
              </div>
              <div className="tb-field">
                <label>Description</label>
                <input placeholder="Internal description..." value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
              </div>
            </div>

            {/* Header */}
            <div className="tb-section">
              <div className="tb-section-title">
                <span>Message Header</span>
                <Badge variant="gray" size="sm">Optional</Badge>
              </div>
              <div className="tb-header-options">
                {['none', 'text', 'image', 'video', 'document'].map(type => (
                  <label key={type} className={`tb-radio ${form.header.type === type ? 'tb-radio--active' : ''}`}>
                    <input type="radio" name="header_type" checked={form.header.type === type} onChange={() => setForm(f => ({ ...f, header: { type } }))} />
                    <span>{type.charAt(0).toUpperCase() + type.slice(1)}</span>
                  </label>
                ))}
              </div>
              {form.header.type === 'text' && (
                <input
                  className="tb-header-input"
                  placeholder="Header text (max 60 chars)"
                  value={form.header.text || ''}
                  onChange={e => setForm(f => ({ ...f, header: { ...f.header, text: e.target.value.slice(0, 60) } }))}
                  maxLength={60}
                />
              )}
              {['image', 'video', 'document'].includes(form.header.type) && (
                <div className="tb-media-note">
                  <span>Media will be uploaded when sending via Meta API. For preview, a placeholder is shown.</span>
                </div>
              )}
            </div>

            {/* Body */}
            <div className="tb-section">
              <div className="tb-section-title">
                <span>Message Body *</span>
                <span className="tb-field-hint">{form.body.length}/1024</span>
              </div>
              <div className="tb-body-wrapper">
                <textarea
                  placeholder="Type your message here. Use {{1}}, {{2}} for dynamic variables..."
                  value={form.body}
                  onChange={e => setForm({ ...form, body: e.target.value.slice(0, 1024) })}
                  rows={5}
                  maxLength={1024}
                  required
                />
                <div className="tb-body-toolbar">
                  <button type="button" className="tb-toolbar-btn" onClick={insertVariable} title="Add variable">
                    <Variable size={14} />
                    <span>Add Variable</span>
                  </button>
                  <button type="button" className="tb-toolbar-btn" title="Emoji">
                    <Smile size={14} />
                  </button>
                  <button type="button" className="tb-toolbar-btn" title="Bold">
                    <Bold size={14} />
                  </button>
                  <button type="button" className="tb-toolbar-btn" title="Italic">
                    <Italic size={14} />
                  </button>
                </div>
              </div>
              {/* Variable mapping */}
              {(form.body.match(/\{\{\d+\}\}/g) || []).length > 0 && (
                <div className="tb-variables">
                  <span className="tb-variables-label">Variables detected:</span>
                  {(form.body.match(/\{\{(\d+)\}\}/g) || []).map((v, i) => (
                    <Badge key={i} variant="primary" size="sm">{v} → {VARIABLE_PRESETS[i]?.label || `Variable ${i + 1}`}</Badge>
                  ))}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="tb-section">
              <div className="tb-section-title">
                <span>Footer</span>
                <Badge variant="gray" size="sm">Optional</Badge>
                <span className="tb-field-hint">{(form.footer || '').length}/60</span>
              </div>
              <input
                placeholder="Add a tagline, unsubscribe note, etc."
                value={form.footer}
                onChange={e => setForm({ ...form, footer: e.target.value.slice(0, 60) })}
                maxLength={60}
              />
            </div>

            {/* Buttons */}
            <div className="tb-section">
              <div className="tb-section-title">
                <span>Buttons</span>
                <Badge variant="gray" size="sm">Optional · Max 3</Badge>
              </div>
              <p className="tb-section-desc">Create buttons that let customers respond to your message or take action.</p>

              {form.buttons.map((btn, i) => (
                <div key={i} className="tb-button-row">
                  <Badge variant={btn.type === 'quick_reply' ? 'primary' : btn.type === 'url' ? 'success' : 'orange'} size="sm">
                    {btn.type === 'quick_reply' ? 'Quick Reply' : btn.type === 'url' ? 'URL' : 'Phone'}
                  </Badge>
                  <input
                    placeholder="Button text"
                    value={btn.text}
                    onChange={e => updateButton(i, 'text', e.target.value)}
                  />
                  {btn.type === 'url' && (
                    <input placeholder="https://..." value={btn.url || ''} onChange={e => updateButton(i, 'url', e.target.value)} />
                  )}
                  {btn.type === 'phone' && (
                    <input placeholder="+919876543210" value={btn.phone || ''} onChange={e => updateButton(i, 'phone', e.target.value)} />
                  )}
                  <button className="tb-button-remove" onClick={() => removeButton(i)}>
                    <X size={14} />
                  </button>
                </div>
              ))}

              {form.buttons.length < 3 && (
                <div className="tb-button-add-row">
                  <button className="tb-button-add" onClick={() => addButton('quick_reply')}>+ Quick Reply</button>
                  <button className="tb-button-add" onClick={() => addButton('url')}>+ URL Button</button>
                  <button className="tb-button-add" onClick={() => addButton('phone')}>+ Phone Button</button>
                </div>
              )}
              {form.buttons.length > 3 && (
                <p className="tb-warning">If you add more than 3 buttons, they will appear in a list.</p>
              )}
            </div>
          </div>

          {/* Right: WhatsApp Preview */}
          <WhatsAppPreview
            header={form.header}
            body={form.body}
            footer={form.footer}
            buttons={form.buttons}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Main Templates Page ──────────────────────────────────────────
export default function Templates() {
  const { data, loading, refetch } = useApi(() => templateApi.list(), []);
  const [showBuilder, setShowBuilder] = useState(false);
  const [editTemplate, setEditTemplate] = useState(null);
  const [saving, setSaving] = useState(false);
  const [filterCategory, setFilterCategory] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [previewTemplate, setPreviewTemplate] = useState(null);

  const templates = data?.templates || [];
  const stats = data?.stats || {};

  const filtered = useMemo(() => {
    let list = templates;
    if (filterCategory) list = list.filter(t => t.category === filterCategory);
    if (filterStatus) list = list.filter(t => t.approval_status === filterStatus);
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      list = list.filter(t => t.name.toLowerCase().includes(q) || (t.body || '').toLowerCase().includes(q));
    }
    return list;
  }, [templates, filterCategory, filterStatus, searchTerm]);

  async function handleSave(formData) {
    setSaving(true);
    try {
      if (editTemplate) {
        await templateApi.update(editTemplate.id, formData);
      } else {
        await templateApi.create(formData);
      }
      setShowBuilder(false);
      setEditTemplate(null);
      refetch();
    } catch (err) {
      alert(err.message || 'Failed to save template');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this template? This cannot be undone.')) return;
    await templateApi.delete(id);
    refetch();
  }

  function openEdit(t) {
    setEditTemplate(t);
    setShowBuilder(true);
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Templates"
        description="WhatsApp message templates — create, manage, and track performance"
        actions={
          <Button icon={Plus} onClick={() => { setEditTemplate(null); setShowBuilder(true); }}>
            New Template
          </Button>
        }
      />

      {/* Stats Row */}
      <div className="template-stats">
        <StatCard icon={FileText} label="Total" value={stats.total || 0} />
        <StatCard icon={CheckCircle} label="Approved" value={stats.approved || 0} variant="success" />
        <StatCard icon={Clock} label="Pending" value={stats.pending || 0} variant="warning" />
        <StatCard icon={XCircle} label="Rejected" value={stats.rejected || 0} variant="danger" />
        <StatCard icon={Send} label="Total Sends" value={stats.total_usage || 0} />
      </div>

      {/* Filters */}
      <div className="template-filters">
        <div className="template-search">
          <Search size={16} />
          <input placeholder="Search templates..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
        </div>
        <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}>
          <option value="">All Categories</option>
          <option value="utility">Utility</option>
          <option value="marketing">Marketing</option>
          <option value="authentication">Authentication</option>
        </select>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="approved">Approved</option>
          <option value="pending">Pending</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {/* Template Grid */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No templates found"
          description={templates.length === 0 ? 'Create your first WhatsApp message template to get started.' : 'No templates match your current filters.'}
          action={templates.length === 0 && <Button icon={Plus} onClick={() => setShowBuilder(true)}>Create Template</Button>}
        />
      ) : (
        <div className="template-grid">
          {filtered.map(t => {
            const status = STATUS_MAP[t.approval_status] || STATUS_MAP.pending;
            const StatusIcon = status.icon;
            return (
              <div key={t.id} className="tpl-card">
                <div className="tpl-card-top">
                  <div className="tpl-card-meta">
                    <span className="tpl-card-name">{t.name}</span>
                    {t.description && <span className="tpl-card-desc">{t.description}</span>}
                  </div>
                  <div className="tpl-card-badges">
                    <Badge variant={status.variant} size="sm" dot>{status.label}</Badge>
                    <Badge variant="default" size="sm">{t.category}</Badge>
                  </div>
                </div>

                {/* Mini preview */}
                <div className="tpl-card-preview">
                  {t.header && t.header.type !== 'none' && (
                    <div className="tpl-card-header-preview">
                      {t.header.type === 'text' && <strong>{t.header.text}</strong>}
                      {['image', 'video', 'document'].includes(t.header.type) && (
                        <Badge variant="gray" size="sm">{t.header.type}</Badge>
                      )}
                    </div>
                  )}
                  <div className="tpl-card-body">{t.body}</div>
                  {t.footer && <div className="tpl-card-footer-text">{t.footer}</div>}
                  {t.buttons && t.buttons.length > 0 && (
                    <div className="tpl-card-buttons-preview">
                      {t.buttons.map((b, i) => (
                        <span key={i} className="tpl-card-btn-chip">{b.text}</span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Stats bar */}
                <div className="tpl-card-stats">
                  <span title="Times sent"><Send size={12} /> {t.usage_count || 0}</span>
                  <span title="Reply rate"><CornerDownRight size={12} /> {(t.reply_rate || 0).toFixed(0)}%</span>
                  <span className="tpl-card-lang">{LANGUAGES.find(l => l.code === t.language)?.label || t.language}</span>
                </div>

                {/* Actions */}
                <div className="tpl-card-actions">
                  <button className="tpl-action-btn" onClick={() => setPreviewTemplate(t)} title="Preview">
                    <Eye size={14} />
                  </button>
                  <button className="tpl-action-btn" onClick={() => openEdit(t)} title="Edit">
                    <Edit size={14} />
                  </button>
                  <button className="tpl-action-btn tpl-action-btn--danger" onClick={() => handleDelete(t.id)} title="Delete">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Preview Modal */}
      {previewTemplate && (
        <div className="template-builder-overlay" onClick={() => setPreviewTemplate(null)}>
          <div className="template-preview-modal" onClick={e => e.stopPropagation()}>
            <div className="template-preview-modal-header">
              <h3>{previewTemplate.name}</h3>
              <button onClick={() => setPreviewTemplate(null)}><X size={18} /></button>
            </div>
            <WhatsAppPreview
              header={previewTemplate.header}
              body={previewTemplate.body}
              footer={previewTemplate.footer}
              buttons={previewTemplate.buttons}
            />
          </div>
        </div>
      )}

      {/* Template Builder */}
      {showBuilder && (
        <TemplateBuilder
          template={editTemplate}
          onSave={handleSave}
          onClose={() => { setShowBuilder(false); setEditTemplate(null); }}
          saving={saving}
        />
      )}
    </div>
  );
}
