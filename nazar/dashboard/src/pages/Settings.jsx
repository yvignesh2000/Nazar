import { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon, Save, Brain, Bell, Clock, Key, Wifi, WifiOff,
  CheckCircle2, XCircle, Zap, MessageSquare, TestTube, ShieldOff, ShieldCheck,
  ScrollText, Sliders, Link2, Bot, Shield,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { config as configApi, setup as setupApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import './Settings.css';

const API_KEY = 'nazar_dev_key';
function getHeaders() {
  const token = localStorage.getItem('nazar_token');
  return token ? { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'X-Nazar-Key': API_KEY, 'Content-Type': 'application/json' };
}
async function fetchOptouts() { return (await fetch('/api/optouts', { headers: getHeaders() })).json(); }
async function fetchAuditLog(limit = 50) { return (await fetch(`/api/audit?limit=${limit}`, { headers: getHeaders() })).json(); }

const TABS = [
  { id: 'general', label: 'General', icon: Sliders },
  { id: 'integrations', label: 'Integrations', icon: Link2 },
  { id: 'ai', label: 'AI & Bot', icon: Bot },
  { id: 'compliance', label: 'Compliance', icon: Shield },
  { id: 'audit', label: 'Audit Log', icon: ScrollText },
];

export default function Settings() {
  const { data, loading, refetch } = useApi(() => configApi.get(), []);
  const { data: setupStatus, refetch: refetchSetup } = useApi(() => setupApi.status(), []);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeTab, setActiveTab] = useState('general');

  // API Keys state
  const [keys, setKeys] = useState({ OPENROUTER_API_KEY: '', ANTHROPIC_API_KEY: '', GOOGLE_API_KEY: '', GROQ_API_KEY: '', WA_PHONE_NUMBER_ID: '', WA_ACCESS_TOKEN: '' });
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysSaved, setKeysSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => { if (data) setForm(data); }, [data]);

  function updateField(field, value) { setForm(prev => ({ ...prev, [field]: value })); setSaved(false); }
  function updateKey(field, value) { setKeys(prev => ({ ...prev, [field]: value })); setKeysSaved(false); }

  async function handleSave() {
    setSaving(true);
    try { await configApi.update(form); setSaved(true); refetch(); setTimeout(() => setSaved(false), 3000); }
    catch (err) { alert('Save failed: ' + err.message); }
    finally { setSaving(false); }
  }

  async function handleSaveKeys() {
    setSavingKeys(true);
    try {
      const nonEmpty = {};
      for (const [k, v] of Object.entries(keys)) { if (v.trim()) nonEmpty[k] = v.trim(); }
      if (Object.keys(nonEmpty).length === 0) { alert('Enter at least one key'); return; }
      await setupApi.saveKeys(nonEmpty);
      setKeysSaved(true);
      refetchSetup();
      setKeys({ OPENROUTER_API_KEY: '', ANTHROPIC_API_KEY: '', GOOGLE_API_KEY: '', GROQ_API_KEY: '', WA_PHONE_NUMBER_ID: '', WA_ACCESS_TOKEN: '' });
      setTimeout(() => setKeysSaved(false), 3000);
    } catch (err) { alert('Save keys failed: ' + err.message); }
    finally { setSavingKeys(false); }
  }

  async function handleTestLlm() {
    setTesting(true); setTestResult(null);
    try { setTestResult(await setupApi.testLlm()); }
    catch (err) { setTestResult({ ok: false, error: err.message }); }
    finally { setTesting(false); }
  }

  if (loading) return <Spinner />;

  const ss = setupStatus || {};
  const llm = ss.llm || {};
  const wa = ss.whatsapp || {};

  return (
    <div className="page-content">
      <PageHeader
        title="Settings"
        description="Configure your workspace, integrations, and bot behavior"
        actions={<Button icon={Save} loading={saving} onClick={handleSave}>{saved ? 'Saved!' : 'Save Settings'}</Button>}
      />

      {/* Tab navigation */}
      <div className="settings-tabs">
        {TABS.map(t => {
          const Icon = t.icon;
          return (
            <button key={t.id} className={`settings-tab ${activeTab === t.id ? 'settings-tab--active' : ''}`} onClick={() => setActiveTab(t.id)}>
              <Icon size={15} /><span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* ── General Tab ── */}
      {activeTab === 'general' && (
        <div className="settings-panel">
          <div className="settings-section">
            <h2 className="settings-section-title"><SettingsIcon size={18} /> General</h2>
            <div className="settings-fields">
              <div className="settings-field"><label>Business Name</label><input value={form.business_name || ''} onChange={e => updateField('business_name', e.target.value)} /></div>
              <div className="settings-field"><label>Welcome Message</label><textarea value={form.welcome_message || ''} onChange={e => updateField('welcome_message', e.target.value)} rows={2} /></div>
              <div className="settings-field">
                <label>Bot Persona</label>
                <select value={form.bot_persona || 'professional'} onChange={e => updateField('bot_persona', e.target.value)}>
                  <option value="professional">Professional</option>
                  <option value="friendly">Friendly</option>
                  <option value="casual">Casual</option>
                </select>
              </div>
              <div className="settings-toggle">
                <div><span className="settings-toggle-label">Bot Enabled</span><span className="settings-toggle-desc">Enable AI-powered auto-replies to customer messages</span></div>
                <button className={`toggle ${form.bot_enabled ? 'toggle--on' : ''}`} onClick={() => updateField('bot_enabled', !form.bot_enabled)}><span className="toggle-thumb" /></button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Integrations Tab ── */}
      {activeTab === 'integrations' && (
        <div className="settings-panel">
          {/* Setup Status */}
          <div className="settings-section settings-section--highlight">
            <h2 className="settings-section-title"><Zap size={18} /> Connection Status</h2>
            <div className="settings-fields">
              <div className="setup-status-grid">
                <div className="setup-status-item">
                  {ss.any_llm_configured ? <CheckCircle2 size={18} className="status-icon status-icon--ok" /> : <XCircle size={18} className="status-icon status-icon--bad" />}
                  <div><span className="setup-label">AI Provider</span><span className="setup-detail">{ss.any_llm_configured ? 'Connected — AI replies active' : 'Not configured — add an API key below'}</span></div>
                </div>
                <div className="setup-status-item">
                  {wa.configured ? <Wifi size={18} className="status-icon status-icon--ok" /> : <WifiOff size={18} className="status-icon status-icon--warn" />}
                  <div><span className="setup-label">WhatsApp</span><span className="setup-detail">{wa.configured ? 'Connected — receiving messages' : 'Not connected — use Test Mode to simulate'}</span></div>
                </div>
              </div>
              <div className="provider-grid">
                {Object.entries(llm).map(([name, info]) => (
                  <div key={name} className={`provider-chip ${info.configured ? 'provider-chip--ok' : ''}`}>
                    <span className="provider-dot" style={{ background: info.configured ? 'var(--color-success-500)' : 'var(--color-gray-300)' }} />
                    <span className="provider-name">{name}</span>
                    {info.configured && <Badge variant="success" size="sm">Active</Badge>}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* API Keys */}
          <div className="settings-section">
            <h2 className="settings-section-title"><Key size={18} /> API Keys</h2>
            <div className="settings-fields">
              <p className="settings-section-desc">Add at least one AI provider key. Keys are saved to <code>.env</code> on the server.</p>
              <div className="settings-field">
                <label>OpenRouter API Key <Badge variant={llm.openrouter?.configured ? 'success' : 'gray'} size="sm">{llm.openrouter?.configured ? 'Set' : 'Not set'}</Badge></label>
                <input type="password" placeholder={llm.openrouter?.configured ? '••••••••  (saved)' : 'sk-or-v1-...'} value={keys.OPENROUTER_API_KEY} onChange={e => updateKey('OPENROUTER_API_KEY', e.target.value)} />
                <span className="settings-field-help">Best option — routes to multiple models. <a href="https://openrouter.ai/keys" target="_blank" rel="noopener">Get key</a></span>
              </div>
              <div className="settings-field"><label>Anthropic API Key <Badge variant={llm.anthropic?.configured ? 'success' : 'gray'} size="sm">{llm.anthropic?.configured ? 'Set' : 'Not set'}</Badge></label><input type="password" placeholder={llm.anthropic?.configured ? '••••••••  (saved)' : 'sk-ant-...'} value={keys.ANTHROPIC_API_KEY} onChange={e => updateKey('ANTHROPIC_API_KEY', e.target.value)} /></div>
              <div className="settings-field"><label>Google Gemini API Key <Badge variant={llm.google?.configured ? 'success' : 'gray'} size="sm">{llm.google?.configured ? 'Set' : 'Not set'}</Badge></label><input type="password" placeholder={llm.google?.configured ? '••••••••  (saved)' : 'AIza...'} value={keys.GOOGLE_API_KEY} onChange={e => updateKey('GOOGLE_API_KEY', e.target.value)} /></div>
              <div className="settings-field"><label>Groq API Key (voice) <Badge variant={ss.groq?.configured ? 'success' : 'gray'} size="sm">{ss.groq?.configured ? 'Set' : 'Not set'}</Badge></label><input type="password" placeholder={ss.groq?.configured ? '••••••••  (saved)' : 'gsk_...'} value={keys.GROQ_API_KEY} onChange={e => updateKey('GROQ_API_KEY', e.target.value)} /></div>
              <div className="settings-btn-row">
                <Button icon={Save} loading={savingKeys} onClick={handleSaveKeys}>{keysSaved ? 'Keys Saved!' : 'Save Keys'}</Button>
                <Button icon={TestTube} variant="secondary" loading={testing} onClick={handleTestLlm}>Test AI Connection</Button>
              </div>
              {testResult && (
                <div className={`test-result ${testResult.ok ? 'test-result--ok' : 'test-result--fail'}`}>
                  {testResult.ok ? <><CheckCircle2 size={16} /><div><strong>AI Connected!</strong><p>{testResult.response}</p></div></> : <><XCircle size={16} /><div><strong>Connection Failed</strong><p>{testResult.error || 'No AI provider responded.'}</p></div></>}
                </div>
              )}
            </div>
          </div>

          {/* WhatsApp */}
          <div className="settings-section">
            <h2 className="settings-section-title"><MessageSquare size={18} /> WhatsApp Cloud API</h2>
            <div className="settings-fields">
              <p className="settings-section-desc">Connect your WhatsApp Business account. Without this, you can still test using Test Mode in any conversation.</p>
              <div className="settings-field"><label>Phone Number ID <Badge variant={wa.phone_number_id ? 'success' : 'gray'} size="sm">{wa.phone_number_id ? 'Set' : 'Not set'}</Badge></label><input placeholder={wa.phone_number_id ? '••••••••  (saved)' : 'From Meta Business Suite'} value={keys.WA_PHONE_NUMBER_ID} onChange={e => updateKey('WA_PHONE_NUMBER_ID', e.target.value)} /></div>
              <div className="settings-field"><label>Access Token <Badge variant={wa.configured ? 'success' : 'gray'} size="sm">{wa.configured ? 'Set' : 'Not set'}</Badge></label><input type="password" placeholder={wa.configured ? '••••••••  (saved)' : 'Permanent token from Meta'} value={keys.WA_ACCESS_TOKEN} onChange={e => updateKey('WA_ACCESS_TOKEN', e.target.value)} /><span className="settings-field-help">Get from Meta Business Suite → WhatsApp → API Setup</span></div>
              <Button icon={Save} loading={savingKeys} onClick={handleSaveKeys}>{keysSaved ? 'Saved!' : 'Save WhatsApp Keys'}</Button>
            </div>
          </div>
        </div>
      )}

      {/* ── AI & Bot Tab ── */}
      {activeTab === 'ai' && (
        <div className="settings-panel">
          <div className="settings-section">
            <h2 className="settings-section-title"><Brain size={18} /> Escalation Rules</h2>
            <div className="settings-fields">
              <p className="settings-section-desc">Configure when the AI should stop replying and alert a human team member.</p>
              <div className="settings-toggle">
                <div><span className="settings-toggle-label">Auto-detect when to escalate</span><span className="settings-toggle-desc">AI detects frustration, complex queries, and requests to speak with a person</span></div>
                <button className={`toggle ${form.smart_handoff ? 'toggle--on' : ''}`} onClick={() => updateField('smart_handoff', !form.smart_handoff)}><span className="toggle-thumb" /></button>
              </div>
              <div className="settings-field"><label>Escalation Message</label><textarea value={form.handoff_message || ''} onChange={e => updateField('handoff_message', e.target.value)} rows={2} /><span className="settings-field-help">Sent to the customer when the bot escalates to a human</span></div>
              <div className="settings-field"><label><Bell size={14} /> Notification Phone</label><input placeholder="+91XXXXXXXXXX" value={form.notify_phone || ''} onChange={e => updateField('notify_phone', e.target.value)} /><span className="settings-field-help">WhatsApp number to receive escalation alerts</span></div>
              <div className="settings-field"><label><Clock size={14} /> Auto-resume AI (hours)</label><input type="number" min="0" value={form.auto_resume_hours || 0} onChange={e => updateField('auto_resume_hours', parseInt(e.target.value) || 0)} /><span className="settings-field-help">Automatically turn the bot back on after X hours (0 = manual only)</span></div>
            </div>
          </div>

          <div className="settings-section">
            <h2 className="settings-section-title"><Brain size={18} /> AI Features</h2>
            <div className="settings-fields">
              <div className="settings-toggle">
                <div><span className="settings-toggle-label">Customer Memory</span><span className="settings-toggle-desc">AI remembers customer context across conversations for personalized replies</span></div>
                <button className={`toggle ${form.memory_enabled ? 'toggle--on' : ''}`} onClick={() => updateField('memory_enabled', !form.memory_enabled)}><span className="toggle-thumb" /></button>
              </div>
              <div className="settings-toggle">
                <div><span className="settings-toggle-label">Detect Buying Intent</span><span className="settings-toggle-desc">AI identifies buying signals, pricing questions, and urgency indicators</span></div>
                <button className={`toggle ${form.signal_detection ? 'toggle--on' : ''}`} onClick={() => updateField('signal_detection', !form.signal_detection)}><span className="toggle-thumb" /></button>
              </div>
              <div className="settings-toggle">
                <div><span className="settings-toggle-label">Auto Lead Scoring</span><span className="settings-toggle-desc">Automatically score leads 0-100 based on engagement and buying signals</span></div>
                <button className={`toggle ${form.auto_lead_scoring ? 'toggle--on' : ''}`} onClick={() => updateField('auto_lead_scoring', !form.auto_lead_scoring)}><span className="toggle-thumb" /></button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Compliance Tab ── */}
      {activeTab === 'compliance' && (
        <div className="settings-panel">
          <OptoutsSection />
        </div>
      )}

      {/* ── Audit Log Tab ── */}
      {activeTab === 'audit' && (
        <div className="settings-panel">
          <AuditSection />
        </div>
      )}
    </div>
  );
}

/* ── Opt-out Management Section ────────────────────────────────── */
function OptoutsSection() {
  const [optouts, setOptouts] = useState(null);
  const [loadingOpt, setLoadingOpt] = useState(true);

  useEffect(() => {
    fetchOptouts().then(data => setOptouts(data)).catch(() => setOptouts({ optouts: [], count: 0 })).finally(() => setLoadingOpt(false));
  }, []);

  if (loadingOpt) return <div className="settings-section"><h2 className="settings-section-title"><ShieldOff size={18} /> Opt-out Management</h2><Spinner /></div>;

  const list = optouts?.optouts || [];

  return (
    <div className="settings-section">
      <h2 className="settings-section-title"><ShieldOff size={18} /> Opt-out Management {list.length > 0 && <Badge variant="orange" size="sm">{list.length} opted out</Badge>}</h2>
      <div className="settings-fields">
        <p className="settings-section-desc">Contacts who reply <strong>STOP</strong> are automatically opted out. Nazar won't send them any messages. They can opt back in by replying <strong>START</strong>.</p>
        {list.length === 0 ? (
          <div className="settings-empty-notice"><ShieldCheck size={16} /><span>No contacts have opted out. All contacts are reachable.</span></div>
        ) : (
          <div className="optout-table-wrap"><table className="optout-table"><thead><tr><th>Phone</th><th>Opted Out</th></tr></thead><tbody>
            {list.map((item, i) => <tr key={i}><td>{item.phone}</td><td className="text-muted">{item.opted_out_at ? new Date(item.opted_out_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'}</td></tr>)}
          </tbody></table></div>
        )}
      </div>
    </div>
  );
}

/* ── Audit Log Section ─────────────────────────────────────────── */
function AuditSection() {
  const [auditLog, setAuditLog] = useState(null);
  const [loadingAudit, setLoadingAudit] = useState(true);

  useEffect(() => {
    fetchAuditLog(30).then(data => setAuditLog(data)).catch(() => setAuditLog({ entries: [] })).finally(() => setLoadingAudit(false));
  }, []);

  if (loadingAudit) return <div className="settings-section"><h2 className="settings-section-title"><ScrollText size={18} /> Audit Log</h2><Spinner /></div>;

  const entries = auditLog?.entries || [];
  const actionBadge = (action) => {
    if (action?.includes('create') || action?.includes('add')) return 'success';
    if (action?.includes('delete') || action?.includes('remove')) return 'danger';
    if (action?.includes('update') || action?.includes('move')) return 'warning';
    return 'default';
  };

  return (
    <div className="settings-section">
      <h2 className="settings-section-title"><ScrollText size={18} /> Audit Log <Badge variant="gray" size="sm">Last 30 events</Badge></h2>
      <div className="settings-fields">
        <p className="settings-section-desc">Track all important actions — contact changes, campaign sends, stage moves, and more.</p>
        {entries.length === 0 ? (
          <div className="settings-empty-notice"><ScrollText size={16} /><span>No audit events yet. Actions will appear here.</span></div>
        ) : (
          <div className="audit-list">
            {entries.map((e, i) => (
              <div key={i} className="audit-item">
                <div className="audit-item-left"><Badge variant={actionBadge(e.action)} size="sm">{e.action}</Badge><span className="audit-detail">{e.detail || e.entity_id || '—'}</span></div>
                <div className="audit-item-right">{e.actor && <span className="audit-actor">{e.actor}</span>}<span className="audit-time">{e.timestamp ? new Date(e.timestamp).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</span></div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
