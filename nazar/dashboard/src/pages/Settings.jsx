import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Save, Brain, HandMetal, Bell, Clock, Key, Wifi, WifiOff, CheckCircle2, XCircle, Zap, MessageSquare, TestTube } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { config as configApi, setup as setupApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import './Settings.css';

export default function Settings() {
  const { data, loading, refetch } = useApi(() => configApi.get(), []);
  const { data: setupStatus, refetch: refetchSetup } = useApi(() => setupApi.status(), []);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // API Keys state
  const [keys, setKeys] = useState({
    OPENROUTER_API_KEY: '',
    ANTHROPIC_API_KEY: '',
    GOOGLE_API_KEY: '',
    GROQ_API_KEY: '',
    WA_PHONE_NUMBER_ID: '',
    WA_ACCESS_TOKEN: '',
  });
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysSaved, setKeysSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  function updateField(field, value) {
    setForm(prev => ({ ...prev, [field]: value }));
    setSaved(false);
  }

  function updateKey(field, value) {
    setKeys(prev => ({ ...prev, [field]: value }));
    setKeysSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await configApi.update(form);
      setSaved(true);
      refetch();
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      alert('Save failed: ' + err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveKeys() {
    setSavingKeys(true);
    try {
      // Only send non-empty keys
      const nonEmpty = {};
      for (const [k, v] of Object.entries(keys)) {
        if (v.trim()) nonEmpty[k] = v.trim();
      }
      if (Object.keys(nonEmpty).length === 0) {
        alert('Enter at least one API key');
        return;
      }
      await setupApi.saveKeys(nonEmpty);
      setKeysSaved(true);
      refetchSetup();
      // Clear inputs after save
      setKeys({
        OPENROUTER_API_KEY: '',
        ANTHROPIC_API_KEY: '',
        GOOGLE_API_KEY: '',
        GROQ_API_KEY: '',
        WA_PHONE_NUMBER_ID: '',
        WA_ACCESS_TOKEN: '',
      });
      setTimeout(() => setKeysSaved(false), 3000);
    } catch (err) {
      alert('Save keys failed: ' + err.message);
    } finally {
      setSavingKeys(false);
    }
  }

  async function handleTestLlm() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await setupApi.testLlm();
      setTestResult(res);
    } catch (err) {
      setTestResult({ ok: false, error: err.message });
    } finally {
      setTesting(false);
    }
  }

  if (loading) return <Spinner />;

  const ss = setupStatus || {};
  const llm = ss.llm || {};
  const wa = ss.whatsapp || {};

  return (
    <div className="page-content">
      <PageHeader
        title="Settings"
        description="Configure your bot, API keys, and integrations"
        actions={
          <Button icon={Save} loading={saving} onClick={handleSave}>
            {saved ? 'Saved!' : 'Save Settings'}
          </Button>
        }
      />

      <div className="settings-grid">
        {/* ==========  SETUP STATUS  ========== */}
        <div className="settings-section settings-section--highlight">
          <h2 className="settings-section-title">
            <Zap size={18} /> Setup Status
          </h2>
          <div className="settings-fields">
            <div className="setup-status-grid">
              <div className="setup-status-item">
                {ss.any_llm_configured ? (
                  <CheckCircle2 size={18} className="status-icon status-icon--ok" />
                ) : (
                  <XCircle size={18} className="status-icon status-icon--bad" />
                )}
                <div>
                  <span className="setup-label">LLM Provider</span>
                  <span className="setup-detail">
                    {ss.any_llm_configured ? 'Connected — AI replies active' : 'Not configured — add an API key below'}
                  </span>
                </div>
              </div>
              <div className="setup-status-item">
                {wa.configured ? (
                  <Wifi size={18} className="status-icon status-icon--ok" />
                ) : (
                  <WifiOff size={18} className="status-icon status-icon--warn" />
                )}
                <div>
                  <span className="setup-label">WhatsApp</span>
                  <span className="setup-detail">
                    {wa.configured ? 'Connected — receiving messages' : 'Not connected — use Simulation mode to test'}
                  </span>
                </div>
              </div>
              <div className="setup-status-item">
                {ss.groq?.configured ? (
                  <CheckCircle2 size={18} className="status-icon status-icon--ok" />
                ) : (
                  <XCircle size={18} className="status-icon status-icon--muted" />
                )}
                <div>
                  <span className="setup-label">Voice Transcription</span>
                  <span className="setup-detail">
                    {ss.groq?.configured ? 'Groq Whisper active' : 'Optional — add GROQ_API_KEY for voice notes'}
                  </span>
                </div>
              </div>
            </div>

            {/* LLM Provider details */}
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

        {/* ==========  API KEYS  ========== */}
        <div className="settings-section">
          <h2 className="settings-section-title">
            <Key size={18} /> API Keys
          </h2>
          <div className="settings-fields">
            <p className="settings-section-desc">
              Add at least one LLM provider key. Keys are saved to <code>.env</code> on the server.
              Values are masked after saving — enter a new value to update.
            </p>
            <div className="settings-field">
              <label>OpenRouter API Key <Badge variant={llm.openrouter?.configured ? 'success' : 'gray'} size="sm">{llm.openrouter?.configured ? 'Set' : 'Not set'}</Badge></label>
              <input
                type="password"
                placeholder={llm.openrouter?.configured ? '••••••••  (saved — enter new to update)' : 'sk-or-v1-...'}
                value={keys.OPENROUTER_API_KEY}
                onChange={e => updateKey('OPENROUTER_API_KEY', e.target.value)}
              />
              <span className="settings-field-help">Best option — routes to multiple models with failover. Get key from <a href="https://openrouter.ai/keys" target="_blank" rel="noopener">openrouter.ai/keys</a></span>
            </div>
            <div className="settings-field">
              <label>Anthropic API Key <Badge variant={llm.anthropic?.configured ? 'success' : 'gray'} size="sm">{llm.anthropic?.configured ? 'Set' : 'Not set'}</Badge></label>
              <input
                type="password"
                placeholder={llm.anthropic?.configured ? '••••••••  (saved)' : 'sk-ant-...'}
                value={keys.ANTHROPIC_API_KEY}
                onChange={e => updateKey('ANTHROPIC_API_KEY', e.target.value)}
              />
            </div>
            <div className="settings-field">
              <label>Google Gemini API Key <Badge variant={llm.google?.configured ? 'success' : 'gray'} size="sm">{llm.google?.configured ? 'Set' : 'Not set'}</Badge></label>
              <input
                type="password"
                placeholder={llm.google?.configured ? '••••••••  (saved)' : 'AIza...'}
                value={keys.GOOGLE_API_KEY}
                onChange={e => updateKey('GOOGLE_API_KEY', e.target.value)}
              />
            </div>
            <div className="settings-field">
              <label>Groq API Key (voice transcription) <Badge variant={ss.groq?.configured ? 'success' : 'gray'} size="sm">{ss.groq?.configured ? 'Set' : 'Not set'}</Badge></label>
              <input
                type="password"
                placeholder={ss.groq?.configured ? '••••••••  (saved)' : 'gsk_...'}
                value={keys.GROQ_API_KEY}
                onChange={e => updateKey('GROQ_API_KEY', e.target.value)}
              />
            </div>

            <div className="settings-btn-row">
              <Button icon={Save} loading={savingKeys} onClick={handleSaveKeys}>
                {keysSaved ? 'Keys Saved!' : 'Save Keys'}
              </Button>
              <Button icon={TestTube} variant="secondary" loading={testing} onClick={handleTestLlm}>
                Test LLM Connection
              </Button>
            </div>

            {testResult && (
              <div className={`test-result ${testResult.ok ? 'test-result--ok' : 'test-result--fail'}`}>
                {testResult.ok ? (
                  <>
                    <CheckCircle2 size={16} />
                    <div>
                      <strong>LLM Connected!</strong>
                      <p>{testResult.response}</p>
                    </div>
                  </>
                ) : (
                  <>
                    <XCircle size={16} />
                    <div>
                      <strong>Connection Failed</strong>
                      <p>{testResult.error || testResult.response || 'No LLM provider responded. Check your API keys.'}</p>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ==========  WHATSAPP  ========== */}
        <div className="settings-section">
          <h2 className="settings-section-title">
            <MessageSquare size={18} /> WhatsApp Cloud API
          </h2>
          <div className="settings-fields">
            <p className="settings-section-desc">
              Connect your WhatsApp Business account. Without this, you can still test using
              Simulation mode (open any conversation → send a simulated customer message).
            </p>
            <div className="settings-field">
              <label>Phone Number ID <Badge variant={wa.phone_number_id ? 'success' : 'gray'} size="sm">{wa.phone_number_id ? 'Set' : 'Not set'}</Badge></label>
              <input
                placeholder={wa.phone_number_id ? '••••••••  (saved)' : 'From Meta Business Suite'}
                value={keys.WA_PHONE_NUMBER_ID}
                onChange={e => updateKey('WA_PHONE_NUMBER_ID', e.target.value)}
              />
            </div>
            <div className="settings-field">
              <label>Access Token <Badge variant={wa.configured ? 'success' : 'gray'} size="sm">{wa.configured ? 'Set' : 'Not set'}</Badge></label>
              <input
                type="password"
                placeholder={wa.configured ? '••••••••  (saved)' : 'Permanent token from Meta'}
                value={keys.WA_ACCESS_TOKEN}
                onChange={e => updateKey('WA_ACCESS_TOKEN', e.target.value)}
              />
              <span className="settings-field-help">Get from Meta Business Suite → WhatsApp → API Setup</span>
            </div>
            <Button icon={Save} loading={savingKeys} onClick={handleSaveKeys}>
              {keysSaved ? 'Saved!' : 'Save WhatsApp Keys'}
            </Button>
          </div>
        </div>

        {/* ==========  GENERAL  ========== */}
        <div className="settings-section">
          <h2 className="settings-section-title">
            <SettingsIcon size={18} /> General
          </h2>
          <div className="settings-fields">
            <div className="settings-field">
              <label>Business Name</label>
              <input value={form.business_name || ''} onChange={e => updateField('business_name', e.target.value)} />
            </div>
            <div className="settings-field">
              <label>Welcome Message</label>
              <textarea value={form.welcome_message || ''} onChange={e => updateField('welcome_message', e.target.value)} rows={2} />
            </div>
            <div className="settings-field">
              <label>Bot Persona</label>
              <select value={form.bot_persona || 'professional'} onChange={e => updateField('bot_persona', e.target.value)}>
                <option value="professional">Professional</option>
                <option value="friendly">Friendly</option>
                <option value="casual">Casual</option>
              </select>
            </div>
            <div className="settings-toggle">
              <div>
                <span className="settings-toggle-label">Bot Enabled</span>
                <span className="settings-toggle-desc">Enable AI-powered auto-replies</span>
              </div>
              <button
                className={`toggle ${form.bot_enabled ? 'toggle--on' : ''}`}
                onClick={() => updateField('bot_enabled', !form.bot_enabled)}
              >
                <span className="toggle-thumb" />
              </button>
            </div>
          </div>
        </div>

        {/* ==========  HANDOFF  ========== */}
        <div className="settings-section">
          <h2 className="settings-section-title">
            <HandMetal size={18} /> Handoff
          </h2>
          <div className="settings-fields">
            <div className="settings-toggle">
              <div>
                <span className="settings-toggle-label"><Brain size={14} /> Smart Handoff (AI)</span>
                <span className="settings-toggle-desc">Use AI to detect frustration & complex queries</span>
              </div>
              <button
                className={`toggle ${form.smart_handoff ? 'toggle--on' : ''}`}
                onClick={() => updateField('smart_handoff', !form.smart_handoff)}
              >
                <span className="toggle-thumb" />
              </button>
            </div>
            <div className="settings-field">
              <label>Handoff Message</label>
              <textarea value={form.handoff_message || ''} onChange={e => updateField('handoff_message', e.target.value)} rows={2} />
              <span className="settings-field-help">Sent to customer when handoff triggers</span>
            </div>
            <div className="settings-field">
              <label><Bell size={14} /> Team Notification Phone</label>
              <input placeholder="+91XXXXXXXXXX" value={form.notify_phone || ''} onChange={e => updateField('notify_phone', e.target.value)} />
              <span className="settings-field-help">WhatsApp number to receive handoff alerts</span>
            </div>
            <div className="settings-field">
              <label><Clock size={14} /> Auto-Resume Hours</label>
              <input type="number" min="0" value={form.auto_resume_hours || 0} onChange={e => updateField('auto_resume_hours', parseInt(e.target.value) || 0)} />
              <span className="settings-field-help">Auto-resume bot after X hours (0 = disabled)</span>
            </div>
          </div>
        </div>

        {/* ==========  FEATURES  ========== */}
        <div className="settings-section">
          <h2 className="settings-section-title">
            <Brain size={18} /> Features
          </h2>
          <div className="settings-fields">
            <div className="settings-toggle">
              <div>
                <span className="settings-toggle-label">Memory Enabled</span>
                <span className="settings-toggle-desc">Remember customer context across conversations</span>
              </div>
              <button
                className={`toggle ${form.memory_enabled ? 'toggle--on' : ''}`}
                onClick={() => updateField('memory_enabled', !form.memory_enabled)}
              >
                <span className="toggle-thumb" />
              </button>
            </div>
            <div className="settings-toggle">
              <div>
                <span className="settings-toggle-label">Signal Detection</span>
                <span className="settings-toggle-desc">Auto-detect buying signals & intent</span>
              </div>
              <button
                className={`toggle ${form.signal_detection ? 'toggle--on' : ''}`}
                onClick={() => updateField('signal_detection', !form.signal_detection)}
              >
                <span className="toggle-thumb" />
              </button>
            </div>
            <div className="settings-toggle">
              <div>
                <span className="settings-toggle-label">Auto Lead Scoring</span>
                <span className="settings-toggle-desc">Automatically score leads based on engagement</span>
              </div>
              <button
                className={`toggle ${form.auto_lead_scoring ? 'toggle--on' : ''}`}
                onClick={() => updateField('auto_lead_scoring', !form.auto_lead_scoring)}
              >
                <span className="toggle-thumb" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
