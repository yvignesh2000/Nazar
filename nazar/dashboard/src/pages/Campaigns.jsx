import { useState, useMemo } from 'react';
import { Send, Plus, RotateCcw, Search, X, CheckCircle, Clock, Users, ChevronRight, ChevronLeft, Mail, MailOpen, MessageCircle, AlertCircle, Megaphone, FileText, Bot, User, FileEdit, BookOpen, Upload, Sparkles, Shield, Eye } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { campaigns as campaignApi, templates as templateApi, contacts as contactApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import Spinner from '../components/ui/Spinner';
import StatCard from '../components/ui/StatCard';
import './Campaigns.css';

const PIPELINE_STAGES = ['New', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];

const REPLY_MODES = [
  {
    id: 'auto_ai',
    icon: Bot,
    label: 'AI Auto-Reply',
    description: 'AI responds to campaign replies automatically using campaign knowledge base and business context.',
    color: 'var(--color-success-500)',
    bgColor: 'var(--color-success-50)',
    borderColor: 'var(--color-success-200)',
  },
  {
    id: 'ai_draft',
    icon: FileEdit,
    label: 'AI Draft + Human Approval',
    description: 'AI generates a draft reply. A human agent reviews, edits if needed, and approves before sending.',
    color: 'var(--color-primary-500)',
    bgColor: 'var(--color-primary-50)',
    borderColor: 'var(--color-primary-200)',
    recommended: true,
  },
  {
    id: 'human_only',
    icon: User,
    label: 'Human Only',
    description: 'Only human agents reply. AI stays silent. Best for sensitive campaigns or VIP contacts.',
    color: 'var(--color-orange-500)',
    bgColor: 'var(--color-orange-50)',
    borderColor: 'var(--color-orange-200)',
  },
];

// ─── Campaign Wizard ──────────────────────────────────────────────
function CampaignWizard({ onClose, onCreated }) {
  const [step, setStep] = useState(1);
  const [sending, setSending] = useState(false);

  // Step 1: Template selection
  const { data: tplData, loading: tplLoading } = useApi(() => templateApi.list({ status: 'approved' }), []);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [tplSearch, setTplSearch] = useState('');

  // Step 2: Audience
  const { data: contactData, loading: contactsLoading } = useApi(() => contactApi.list(), []);
  const [filterStage, setFilterStage] = useState('');
  const [filterTag, setFilterTag] = useState('');
  const [selectedContactIds, setSelectedContactIds] = useState([]);
  const [selectAll, setSelectAll] = useState(true);

  // Step 3: Reply Configuration
  const [replyMode, setReplyMode] = useState('ai_draft');
  const [campaignKb, setCampaignKb] = useState('');

  // Step 4: Review
  const [campaignName, setCampaignName] = useState('');

  const allTemplates = tplData?.templates || [];
  const approvedTemplates = allTemplates.filter(t => t.approval_status === 'approved');
  const filteredTemplates = useMemo(() => {
    if (!tplSearch) return approvedTemplates;
    const q = tplSearch.toLowerCase();
    return approvedTemplates.filter(t => t.name.includes(q) || (t.body || '').toLowerCase().includes(q));
  }, [approvedTemplates, tplSearch]);

  const allContacts = contactData?.contacts || [];
  const filteredContacts = useMemo(() => {
    let list = allContacts;
    if (filterStage) list = list.filter(c => c.pipeline_stage === filterStage);
    if (filterTag) list = list.filter(c => (c.tags || []).some(tag => tag.toLowerCase().includes(filterTag.toLowerCase())));
    return list;
  }, [allContacts, filterStage, filterTag]);

  const targetContacts = selectAll ? filteredContacts : filteredContacts.filter(c => selectedContactIds.includes(c.contact_id));
  const targetCount = targetContacts.length;

  function toggleContact(id) {
    setSelectAll(false);
    setSelectedContactIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  function toggleAllContacts() {
    if (selectAll) {
      setSelectAll(false);
      setSelectedContactIds([]);
    } else {
      setSelectAll(true);
      setSelectedContactIds([]);
    }
  }

  async function handleSend() {
    if (!selectedTemplate || targetCount === 0) return;
    setSending(true);
    try {
      const payload = {
        name: campaignName || `Campaign ${new Date().toLocaleDateString()}`,
        template_id: selectedTemplate.id,
        filter_stage: filterStage || undefined,
        filter_tag: filterTag || undefined,
        reply_mode: replyMode,
        campaign_kb: campaignKb || undefined,
      };
      if (!selectAll && selectedContactIds.length > 0) {
        payload.contact_ids = selectedContactIds;
      }
      await campaignApi.create(payload);
      onCreated();
    } catch (err) {
      alert(err.message || 'Failed to send campaign');
    } finally {
      setSending(false);
    }
  }

  const replyModeInfo = REPLY_MODES.find(m => m.id === replyMode);

  const TOTAL_STEPS = 4;

  return (
    <div className="campaign-wizard-overlay">
      <div className="campaign-wizard">
        {/* Stepper */}
        <div className="cw-stepper">
          {[
            { num: 1, label: 'Select Template' },
            { num: 2, label: 'Select Audience' },
            { num: 3, label: 'Configure Replies' },
            { num: 4, label: 'Review & Send' },
          ].map((s, i) => (
            <div key={s.num} className="cw-step-group">
              {i > 0 && <div className="cw-step-line" />}
              <div className={`cw-step ${step >= s.num ? 'cw-step--active' : ''} ${step > s.num ? 'cw-step--done' : ''}`}>
                <span className="cw-step-num">{s.num}</span>
                <span className="cw-step-label">{s.label}</span>
              </div>
            </div>
          ))}
          <button className="cw-close" onClick={onClose}><X size={18} /></button>
        </div>

        {/* Step Content */}
        <div className="cw-content">
          {/* STEP 1: Select Template */}
          {step === 1 && (
            <div className="cw-step-content">
              <div className="cw-step-header">
                <h3>Select Template</h3>
                <div className="cw-search">
                  <Search size={14} />
                  <input placeholder="Search templates..." value={tplSearch} onChange={e => setTplSearch(e.target.value)} />
                </div>
              </div>
              {tplLoading ? <Spinner /> : (
                <div className="cw-template-grid">
                  {filteredTemplates.length === 0 ? (
                    <EmptyState icon={FileText} title="No approved templates" description="Create and get templates approved before sending campaigns." />
                  ) : filteredTemplates.map(t => (
                    <div
                      key={t.id}
                      className={`cw-template-card ${selectedTemplate?.id === t.id ? 'cw-template-card--selected' : ''}`}
                      onClick={() => setSelectedTemplate(t)}
                    >
                      <div className="cw-tc-top">
                        <span className="cw-tc-name">{t.name}</span>
                        <div className="cw-tc-badges">
                          <Badge variant="success" size="sm">Active</Badge>
                          <Badge variant="default" size="sm">{t.category}</Badge>
                        </div>
                      </div>
                      {t.header && t.header.type === 'text' && t.header.text && (
                        <div className="cw-tc-header"><strong>{t.header.text}</strong></div>
                      )}
                      <div className="cw-tc-body">{t.body}</div>
                      {t.footer && <div className="cw-tc-footer">{t.footer}</div>}
                      {t.buttons && t.buttons.length > 0 && (
                        <div className="cw-tc-buttons">
                          {t.buttons.map((b, i) => <span key={i} className="cw-tc-btn">{b.text}</span>)}
                        </div>
                      )}
                      <div className="cw-tc-meta">
                        <span>{t.language}</span>
                        {t.description && <span>· {t.description}</span>}
                      </div>
                      {selectedTemplate?.id === t.id && (
                        <div className="cw-tc-check"><CheckCircle size={18} /></div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* STEP 2: Select Audience */}
          {step === 2 && (
            <div className="cw-step-content">
              <div className="cw-step-header">
                <h3>Select Audience</h3>
                <span className="cw-audience-count">{targetCount} contact{targetCount !== 1 ? 's' : ''} selected</span>
              </div>
              <div className="cw-audience-filters">
                <select value={filterStage} onChange={e => setFilterStage(e.target.value)}>
                  <option value="">All Stages</option>
                  {PIPELINE_STAGES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <input placeholder="Filter by tag..." value={filterTag} onChange={e => setFilterTag(e.target.value)} />
                <label className="cw-select-all">
                  <input type="checkbox" checked={selectAll} onChange={toggleAllContacts} />
                  <span>Select All ({filteredContacts.length})</span>
                </label>
              </div>
              {contactsLoading ? <Spinner /> : (
                <div className="cw-contacts-table-wrap">
                  <table className="cw-contacts-table">
                    <thead>
                      <tr>
                        <th style={{ width: 40 }}></th>
                        <th>Name</th>
                        <th>Phone</th>
                        <th>Stage</th>
                        <th>Tags</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredContacts.length === 0 ? (
                        <tr><td colSpan={5} className="cw-no-contacts">No contacts match filters</td></tr>
                      ) : filteredContacts.map(c => (
                        <tr key={c.contact_id} className={selectAll || selectedContactIds.includes(c.contact_id) ? 'cw-row-selected' : ''}>
                          <td>
                            <input
                              type="checkbox"
                              checked={selectAll || selectedContactIds.includes(c.contact_id)}
                              onChange={() => toggleContact(c.contact_id)}
                            />
                          </td>
                          <td className="cw-contact-name">{c.name || 'Unknown'}</td>
                          <td className="cw-contact-phone">{c.phone}</td>
                          <td><Badge variant="default" size="sm">{c.pipeline_stage || 'New'}</Badge></td>
                          <td>
                            {(c.tags || []).slice(0, 2).map((tag, i) => (
                              <Badge key={i} variant="gray" size="sm">{tag}</Badge>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* STEP 3: Configure Replies */}
          {step === 3 && (
            <div className="cw-step-content">
              <div className="cw-step-header">
                <h3>Configure Reply Handling</h3>
                <p className="cw-step-subtitle">Choose how customer replies to this campaign will be handled</p>
              </div>

              {/* Reply Mode Selection */}
              <div className="cw-reply-modes">
                {REPLY_MODES.map(mode => {
                  const Icon = mode.icon;
                  return (
                    <div
                      key={mode.id}
                      className={`cw-reply-mode-card ${replyMode === mode.id ? 'cw-reply-mode-card--selected' : ''}`}
                      style={{
                        '--mode-color': mode.color,
                        '--mode-bg': mode.bgColor,
                        '--mode-border': replyMode === mode.id ? mode.color : mode.borderColor,
                      }}
                      onClick={() => setReplyMode(mode.id)}
                    >
                      <div className="cw-rm-header">
                        <div className="cw-rm-icon-wrap" style={{ background: mode.bgColor, color: mode.color }}>
                          <Icon size={20} />
                        </div>
                        <div className="cw-rm-text">
                          <div className="cw-rm-label">
                            {mode.label}
                            {mode.recommended && <Badge variant="primary" size="sm">Recommended</Badge>}
                          </div>
                          <div className="cw-rm-desc">{mode.description}</div>
                        </div>
                        <div className={`cw-rm-radio ${replyMode === mode.id ? 'cw-rm-radio--selected' : ''}`}>
                          {replyMode === mode.id && <CheckCircle size={20} />}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Campaign Knowledge Base */}
              <div className="cw-campaign-kb">
                <div className="cw-kb-header">
                  <div className="cw-kb-title">
                    <BookOpen size={18} />
                    <span>Campaign Knowledge Base</span>
                    <Badge variant="gray" size="sm">Optional</Badge>
                  </div>
                  <p className="cw-kb-desc">
                    Add campaign-specific context (product details, pricing, FAQs, offers) that the AI should reference when replying to this campaign.
                    This is used <strong>in addition to</strong> your global knowledge base.
                  </p>
                </div>
                <textarea
                  className="cw-kb-textarea"
                  value={campaignKb}
                  onChange={e => setCampaignKb(e.target.value)}
                  placeholder={`Example:\n\n## Campaign: Summer Sale 2026\n\n- 30% off on all annual plans until June 30\n- Coupon code: SUMMER30\n- Applies to new subscriptions only\n- Existing customers get 20% with code LOYAL20\n- Sale page: example.com/summer-sale\n\n## FAQs\nQ: Can I upgrade my plan during the sale?\nA: Yes! Upgrades are eligible for the discount too.\n\nQ: Is there a refund policy?\nA: Full refund within 14 days, no questions asked.`}
                  rows={8}
                />
                {campaignKb && (
                  <div className="cw-kb-meta">
                    <span>{campaignKb.length} characters</span>
                    {replyMode === 'human_only' && (
                      <span className="cw-kb-warning">
                        <AlertCircle size={12} />
                        KB won't be used in human-only mode (AI doesn't reply)
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 4: Review & Send */}
          {step === 4 && (
            <div className="cw-step-content cw-review">
              <h3>Review & Send Campaign</h3>

              <div className="cw-review-field">
                <label>Campaign Name</label>
                <input
                  placeholder="e.g., April Follow-up Campaign"
                  value={campaignName}
                  onChange={e => setCampaignName(e.target.value)}
                />
              </div>

              <div className="cw-review-summary">
                <div className="cw-review-card">
                  <div className="cw-review-card-label">Template</div>
                  <div className="cw-review-card-value">{selectedTemplate?.name || '—'}</div>
                  <Badge variant="default" size="sm">{selectedTemplate?.category}</Badge>
                </div>
                <div className="cw-review-card">
                  <div className="cw-review-card-label">Recipients</div>
                  <div className="cw-review-card-value">{targetCount}</div>
                  {filterStage && <Badge variant="primary" size="sm">Stage: {filterStage}</Badge>}
                  {filterTag && <Badge variant="primary" size="sm">Tag: {filterTag}</Badge>}
                </div>
                <div className="cw-review-card">
                  <div className="cw-review-card-label">Estimated Cost</div>
                  <div className="cw-review-card-value">
                    ₹{(targetCount * (selectedTemplate?.category === 'marketing' ? 0.70 : 0.15)).toFixed(2)}
                  </div>
                  <span className="cw-review-card-sub">
                    {selectedTemplate?.category === 'marketing' ? '~₹0.70' : '~₹0.15'} per message
                  </span>
                </div>
              </div>

              {/* Reply Mode Summary */}
              <div className="cw-review-reply-mode">
                <div className="cw-review-section-label">Reply Handling</div>
                <div className="cw-review-rm-card" style={{
                  background: replyModeInfo?.bgColor,
                  borderColor: replyModeInfo?.color,
                }}>
                  <replyModeInfo.icon size={18} style={{ color: replyModeInfo?.color }} />
                  <div>
                    <strong>{replyModeInfo?.label}</strong>
                    <p>{replyModeInfo?.description}</p>
                  </div>
                </div>
                {campaignKb && (
                  <div className="cw-review-kb-badge">
                    <BookOpen size={14} />
                    <span>Campaign KB attached ({campaignKb.length} chars)</span>
                  </div>
                )}
              </div>

              {/* Mini template preview */}
              <div className="cw-review-preview">
                <div className="cw-review-preview-label">Message Preview</div>
                <div className="cw-review-bubble">
                  {selectedTemplate?.header?.type === 'text' && selectedTemplate.header.text && (
                    <strong>{selectedTemplate.header.text}</strong>
                  )}
                  <p>{selectedTemplate?.body}</p>
                  {selectedTemplate?.footer && <small>{selectedTemplate.footer}</small>}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Navigation */}
        <div className="cw-footer">
          <div className="cw-footer-left">
            {step > 1 && (
              <Button variant="ghost" icon={ChevronLeft} onClick={() => setStep(s => s - 1)}>
                Back
              </Button>
            )}
          </div>
          <div className="cw-footer-right">
            {step < TOTAL_STEPS ? (
              <Button
                icon={ChevronRight}
                onClick={() => setStep(s => s + 1)}
                disabled={step === 1 && !selectedTemplate}
              >
                {step === 1 ? 'Select Audience' : step === 2 ? 'Configure Replies' : 'Review Campaign'}
              </Button>
            ) : (
              <Button
                icon={Send}
                onClick={handleSend}
                loading={sending}
                disabled={targetCount === 0}
              >
                Send Campaign ({targetCount} contacts)
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Reply Mode Badge Helper ──────────────────────────────────────
function ReplyModeBadge({ mode }) {
  const info = REPLY_MODES.find(m => m.id === mode);
  if (!info) return null;
  const Icon = info.icon;
  return (
    <span className="reply-mode-badge" style={{ background: info.bgColor, color: info.color, border: `1px solid ${info.borderColor}` }}>
      <Icon size={11} />
      <span>{info.label}</span>
    </span>
  );
}

// ─── Main Campaigns Page ──────────────────────────────────────────
export default function Campaigns() {
  const { data, loading, refetch } = useApi(() => campaignApi.list(), []);
  const [showWizard, setShowWizard] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [retargeting, setRetargeting] = useState(null);

  const campaigns = data?.campaigns || [];
  const stats = data?.stats || {};

  const filtered = useMemo(() => {
    if (!searchTerm) return campaigns;
    const q = searchTerm.toLowerCase();
    return campaigns.filter(c =>
      (c.name || '').toLowerCase().includes(q) ||
      (c.template_name || '').toLowerCase().includes(q)
    );
  }, [campaigns, searchTerm]);

  async function handleRetarget(campaignId) {
    setRetargeting(campaignId);
    try {
      await campaignApi.retarget(campaignId, 'failed');
      refetch();
    } catch (err) {
      alert(err.message || 'Retarget failed');
    } finally {
      setRetargeting(null);
    }
  }

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Campaigns"
        description="Send targeted WhatsApp template messages to your contacts"
        actions={
          <Button icon={Plus} onClick={() => setShowWizard(true)}>
            New Campaign
          </Button>
        }
      />

      {/* Overview Stats */}
      <div className="campaign-stats">
        <StatCard icon={Users}          label="Recipients"  value={stats.total_recipients || 0} />
        <StatCard icon={Send}           label="Sent"        value={stats.total_sent || 0} />
        <StatCard icon={Mail}           label="Delivered"   value={stats.total_delivered || 0} sub={stats.delivery_rate ? `${stats.delivery_rate}%` : undefined} variant="success" />
        <StatCard icon={MailOpen}       label="Read"        value={stats.total_read || 0} sub={stats.read_rate ? `${stats.read_rate}%` : undefined} />
        <StatCard icon={MessageCircle}  label="Engaged"     value={stats.total_replied || 0} sub={stats.reply_rate ? `${stats.reply_rate}%` : undefined} variant="primary" />
        <StatCard icon={AlertCircle}    label="Failed"      value={stats.total_failed || 0} variant="danger" />
      </div>

      {/* Search / Filter */}
      <div className="campaign-filters">
        <div className="campaign-search">
          <Search size={16} />
          <input placeholder="Search campaigns..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
        </div>
      </div>

      {/* Campaign Table */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="No campaigns yet"
          description="Launch your first campaign to start reaching your contacts at scale."
          action={<Button icon={Plus} onClick={() => setShowWizard(true)}>Create Campaign</Button>}
        />
      ) : (
        <div className="campaign-table-wrap">
          <table className="campaign-table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Reply Mode</th>
                <th>Status</th>
                <th>Recipients</th>
                <th>Sent</th>
                <th>Delivered</th>
                <th>Read</th>
                <th>Engaged</th>
                <th>Failed</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(c => {
                const deliveryPct = c.sent > 0 ? Math.round((c.delivered || 0) / c.sent * 100) : 0;
                const readPct = c.delivered > 0 ? Math.round((c.read || 0) / c.delivered * 100) : 0;
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="campaign-name-cell">
                        <span className="campaign-name">{c.name || 'Untitled'}</span>
                        <span className="campaign-template">
                          {c.template_name}
                          {c.campaign_kb && <span className="campaign-kb-dot" title="Has campaign KB"><BookOpen size={10} /></span>}
                        </span>
                      </div>
                    </td>
                    <td>
                      <ReplyModeBadge mode={c.reply_mode || 'auto_ai'} />
                    </td>
                    <td>
                      <Badge
                        variant={c.status === 'completed' ? 'success' : c.status === 'scheduled' ? 'warning' : 'gray'}
                        size="sm"
                      >
                        {c.status}
                      </Badge>
                    </td>
                    <td>
                      <div className="campaign-metric">
                        <Users size={13} />
                        <span>{c.target_count}</span>
                      </div>
                    </td>
                    <td>
                      <div className="campaign-metric">
                        <span>{c.sent}</span>
                        <span className="campaign-pct">{c.target_count > 0 ? `${Math.round(c.sent / c.target_count * 100)}%` : ''}</span>
                      </div>
                    </td>
                    <td>
                      <div className="campaign-metric">
                        <div className="campaign-progress">
                          <div className="campaign-progress-bar" style={{ width: `${deliveryPct}%` }} />
                        </div>
                        <span>{c.delivered || 0}</span>
                        <span className="campaign-pct">{deliveryPct}%</span>
                      </div>
                    </td>
                    <td>
                      <div className="campaign-metric">
                        <div className="campaign-progress campaign-progress--blue">
                          <div className="campaign-progress-bar" style={{ width: `${readPct}%` }} />
                        </div>
                        <span>{c.read || 0}</span>
                        <span className="campaign-pct">{readPct}%</span>
                      </div>
                    </td>
                    <td>
                      <span className="campaign-engaged">{c.replied || 0}</span>
                    </td>
                    <td>
                      {c.failed > 0 ? (
                        <span className="campaign-failed">{c.failed}</span>
                      ) : (
                        <span className="campaign-no-fail">0</span>
                      )}
                    </td>
                    <td className="campaign-date">
                      {c.created_at ? new Date(c.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—'}
                    </td>
                    <td>
                      <button
                        className="campaign-retarget-btn"
                        onClick={() => handleRetarget(c.id)}
                        disabled={retargeting === c.id}
                        title="Retarget this campaign"
                      >
                        <RotateCcw size={14} className={retargeting === c.id ? 'spin' : ''} />
                        <span>Retarget</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Campaign Wizard */}
      {showWizard && (
        <CampaignWizard
          onClose={() => setShowWizard(false)}
          onCreated={() => { setShowWizard(false); refetch(); }}
        />
      )}
    </div>
  );
}
