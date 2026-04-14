import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Save, Brain, HandMetal, Bell, Clock } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { config as configApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Spinner from '../components/ui/Spinner';
import './Settings.css';

export default function Settings() {
  const { data, loading, refetch } = useApi(() => configApi.get(), []);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  function updateField(field, value) {
    setForm(prev => ({ ...prev, [field]: value }));
    setSaved(false);
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

  if (loading) return <Spinner />;

  return (
    <div className="page-content">
      <PageHeader
        title="Settings"
        description="Configure your bot and business"
        actions={
          <Button icon={Save} loading={saving} onClick={handleSave}>
            {saved ? 'Saved!' : 'Save Changes'}
          </Button>
        }
      />

      <div className="settings-grid">
        {/* General */}
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

        {/* Handoff Settings */}
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

        {/* Features */}
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
