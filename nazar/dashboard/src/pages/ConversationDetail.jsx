import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Send, Bot, User, HandMetal, Play, AlertTriangle,
  TestTube, FileEdit, CheckCircle, XCircle, RotateCcw,
  BookOpen, ChevronDown, Sparkles, Shield, Eye, Pencil,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import {
  conversations as convApi, handoffs as handoffApi,
  simulate as simApi, replyModes as replyModeApi, drafts as draftApi,
} from '../api/client';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import { format } from 'date-fns';
import './ConversationDetail.css';

const REPLY_MODE_OPTIONS = [
  { id: 'auto_ai', icon: Bot, label: 'AI Auto-Reply', color: 'var(--color-success-600)', badge: 'success' },
  { id: 'ai_draft', icon: FileEdit, label: 'AI Draft + Approve', color: 'var(--color-primary-600)', badge: 'primary' },
  { id: 'human_only', icon: User, label: 'Human Only', color: 'var(--color-orange-600)', badge: 'orange' },
];

export default function ConversationDetail() {
  const { contactId } = useParams();
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [simMode, setSimMode] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simResult, setSimResult] = useState(null);

  // Reply mode
  const [showReplyModeMenu, setShowReplyModeMenu] = useState(false);
  const [changingMode, setChangingMode] = useState(false);

  // Draft review
  const [draftEditing, setDraftEditing] = useState(false);
  const [editedDraft, setEditedDraft] = useState('');
  const [approvingDraft, setApprovingDraft] = useState(false);
  const [rejectingDraft, setRejectingDraft] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const messagesEndRef = useRef(null);
  const replyModeRef = useRef(null);

  const { data, loading, refetch } = useApi(
    () => convApi.get(contactId), [contactId]
  );

  const contact = data?.contact || {};
  const messages = data?.messages || [];
  const botOn = data?.bot_mode !== false;
  const handoffState = data?.handoff_state || null;
  const replyModeInfo = data?.reply_mode || { mode: 'auto_ai', source: 'default' };
  const pendingDraft = data?.pending_draft || null;

  const currentMode = REPLY_MODE_OPTIONS.find(m => m.id === replyModeInfo.mode) || REPLY_MODE_OPTIONS[0];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, simResult, pendingDraft]);

  // Close reply mode menu on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (replyModeRef.current && !replyModeRef.current.contains(e.target)) {
        setShowReplyModeMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // When draft changes, reset editing state
  useEffect(() => {
    if (pendingDraft) {
      setEditedDraft(pendingDraft.draft);
      setDraftEditing(false);
    }
  }, [pendingDraft?.draft]);

  async function handleSend(e) {
    e.preventDefault();
    if (!message.trim() || sending || simulating) return;

    if (simMode) {
      setSimulating(true);
      setSimResult(null);
      try {
        const res = await simApi.message(contactId, message.trim());
        setSimResult(res);
        setMessage('');
        refetch();
      } catch (err) {
        setSimResult({ ok: false, error: err.message });
      } finally {
        setSimulating(false);
      }
    } else {
      setSending(true);
      try {
        await convApi.send(contactId, message.trim());
        setMessage('');
        refetch();
      } catch (err) {
        console.error('Send failed:', err);
      } finally {
        setSending(false);
      }
    }
  }

  async function handleToggleBot() {
    setToggling(true);
    try {
      if (!botOn) {
        await handoffApi.resume(contactId, 'Resumed from chat');
      } else {
        await convApi.handover(contactId, false);
      }
      refetch();
    } catch (err) {
      console.error('Toggle failed:', err);
    } finally {
      setToggling(false);
    }
  }

  async function handleChangeReplyMode(newMode) {
    setChangingMode(true);
    setShowReplyModeMenu(false);
    try {
      await replyModeApi.set(contactId, newMode);
      refetch();
    } catch (err) {
      console.error('Reply mode change failed:', err);
    } finally {
      setChangingMode(false);
    }
  }

  async function handleApproveDraft() {
    setApprovingDraft(true);
    try {
      const textToSend = draftEditing ? editedDraft : '';
      await draftApi.approve(contactId, textToSend);
      refetch();
    } catch (err) {
      console.error('Draft approve failed:', err);
    } finally {
      setApprovingDraft(false);
    }
  }

  async function handleRejectDraft() {
    setRejectingDraft(true);
    try {
      await draftApi.reject(contactId);
      refetch();
    } catch (err) {
      console.error('Draft reject failed:', err);
    } finally {
      setRejectingDraft(false);
    }
  }

  async function handleRegenerateDraft() {
    setRegenerating(true);
    try {
      await draftApi.regenerate(contactId);
      refetch();
    } catch (err) {
      console.error('Draft regenerate failed:', err);
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <div className="chat-page">
      {/* Header */}
      <div className="chat-header">
        <button className="chat-back" onClick={() => navigate('/conversations')}>
          <ArrowLeft size={18} />
        </button>
        <div className="chat-header-avatar">{(contact.name || '?')[0].toUpperCase()}</div>
        <div className="chat-header-info">
          <span className="chat-header-name">{contact.name || 'Unknown'}</span>
          <span className="chat-header-phone">{contact.phone}</span>
        </div>
        <div className="chat-header-actions">
          {!botOn && handoffState?.reason && (
            <Badge variant="orange" size="sm">
              <AlertTriangle size={10} /> {handoffState.reason}
            </Badge>
          )}

          {/* Reply Mode Selector */}
          <div className="reply-mode-selector" ref={replyModeRef}>
            <button
              className="reply-mode-trigger"
              onClick={() => setShowReplyModeMenu(prev => !prev)}
              disabled={changingMode}
              style={{ '--rm-color': currentMode.color }}
            >
              <currentMode.icon size={14} />
              <span>{currentMode.label}</span>
              {replyModeInfo.source === 'campaign' && (
                <span className="rm-source-badge">Campaign</span>
              )}
              <ChevronDown size={12} className={showReplyModeMenu ? 'rm-chevron-up' : ''} />
            </button>

            {showReplyModeMenu && (
              <div className="reply-mode-dropdown">
                <div className="rm-dropdown-header">Reply Mode</div>
                {REPLY_MODE_OPTIONS.map(opt => {
                  const Icon = opt.icon;
                  const isActive = opt.id === replyModeInfo.mode;
                  return (
                    <button
                      key={opt.id}
                      className={`rm-dropdown-item ${isActive ? 'rm-dropdown-item--active' : ''}`}
                      onClick={() => handleChangeReplyMode(opt.id)}
                    >
                      <Icon size={16} style={{ color: opt.color }} />
                      <span>{opt.label}</span>
                      {isActive && <CheckCircle size={14} style={{ color: opt.color }} />}
                    </button>
                  );
                })}
                {replyModeInfo.source !== 'default' && (
                  <div className="rm-dropdown-footer">
                    Currently set by: <strong>{replyModeInfo.source}</strong>
                    {replyModeInfo.campaign_id && (
                      <span className="rm-campaign-tag">
                        <BookOpen size={10} /> Campaign KB active
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          <Button
            size="sm"
            variant={botOn ? 'secondary' : 'success'}
            icon={botOn ? HandMetal : Play}
            loading={toggling}
            onClick={handleToggleBot}
          >
            {botOn ? 'Hand to Human' : 'Resume Bot'}
          </Button>
          <Badge variant={botOn ? 'success' : 'orange'} size="md" dot>
            {botOn ? 'Bot Active' : 'Human Mode'}
          </Badge>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>No messages yet</p>
            <p className="chat-empty-hint">Use <strong>Simulate Customer</strong> mode below to test the AI bot</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`chat-bubble ${msg.direction === 'inbound' ? 'chat-bubble--in' : 'chat-bubble--out'}`}>
              <div className="chat-bubble-content">{msg.content || ''}</div>
              <div className="chat-bubble-meta">
                {msg.sent_by && msg.sent_by !== 'customer' && (
                  <span className="chat-bubble-sender">
                    {msg.sent_by === 'bot' ? <Bot size={10} /> : msg.sent_by === 'bot-approved' ? <><Bot size={10} /><CheckCircle size={8} /></> : <User size={10} />}
                    {msg.sent_by === 'bot-approved' ? 'AI (approved)' : msg.sent_by}
                  </span>
                )}
                <span className="chat-bubble-time">
                  {msg.timestamp ? format(new Date(msg.timestamp), 'h:mm a') : ''}
                </span>
              </div>
            </div>
          ))
        )}

        {/* Pending AI Draft Review Panel */}
        {pendingDraft && pendingDraft.status === 'pending' && (
          <div className="draft-review-panel">
            <div className="draft-review-header">
              <div className="draft-review-title">
                <Sparkles size={16} />
                <span>AI Draft — Pending Approval</span>
              </div>
              <span className="draft-review-time">
                {pendingDraft.generated_at ? format(new Date(pendingDraft.generated_at), 'h:mm a') : ''}
              </span>
            </div>

            {pendingDraft.customer_message && (
              <div className="draft-customer-msg">
                <span className="draft-label">Customer said:</span>
                <p>"{pendingDraft.customer_message}"</p>
              </div>
            )}

            <div className="draft-body">
              <span className="draft-label">AI Draft:</span>
              {draftEditing ? (
                <textarea
                  className="draft-edit-textarea"
                  value={editedDraft}
                  onChange={e => setEditedDraft(e.target.value)}
                  rows={4}
                  autoFocus
                />
              ) : (
                <div className="draft-text">{pendingDraft.draft}</div>
              )}
            </div>

            <div className="draft-actions">
              <div className="draft-actions-left">
                <Button
                  size="sm"
                  variant="success"
                  icon={Send}
                  loading={approvingDraft}
                  onClick={handleApproveDraft}
                >
                  {draftEditing ? 'Send Edited' : 'Approve & Send'}
                </Button>
                {!draftEditing ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={Pencil}
                    onClick={() => setDraftEditing(true)}
                  >
                    Edit
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => { setDraftEditing(false); setEditedDraft(pendingDraft.draft); }}
                  >
                    Cancel Edit
                  </Button>
                )}
              </div>
              <div className="draft-actions-right">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={RotateCcw}
                  loading={regenerating}
                  onClick={handleRegenerateDraft}
                >
                  Regenerate
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  icon={XCircle}
                  loading={rejectingDraft}
                  onClick={handleRejectDraft}
                >
                  Reject
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Sim result notification */}
        {simResult && (
          <div className={`sim-result ${simResult.ok ? '' : 'sim-result--error'}`}>
            {simResult.ok ? (
              simResult.mode === 'handoff' ? (
                <div className="sim-result-body">
                  <AlertTriangle size={14} />
                  <span>Handoff triggered: <strong>{simResult.handoff_reason}</strong></span>
                </div>
              ) : simResult.mode === 'human' || simResult.mode === 'human_only' ? (
                <div className="sim-result-body">
                  <User size={14} />
                  <span>Reply mode is <strong>human-only</strong>. Message saved. No AI response.</span>
                </div>
              ) : simResult.mode === 'ai_draft' ? (
                <div className="sim-result-body">
                  <FileEdit size={14} />
                  <span>AI draft generated. Review it above and approve or edit before sending.</span>
                </div>
              ) : (
                simResult.handoff_triggered && (
                  <div className="sim-result-body">
                    <AlertTriangle size={14} />
                    <span>AI handed off after responding: {simResult.handoff_reason}</span>
                  </div>
                )
              )
            ) : (
              <div className="sim-result-body sim-result-body--error">
                <AlertTriangle size={14} />
                <span>Error: {simResult.error || 'LLM failed. Check API keys in Settings.'}</span>
              </div>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Mode toggle + Input */}
      <div className="chat-input-wrapper">
        <div className="chat-mode-toggle">
          <button
            className={`mode-btn ${!simMode ? 'mode-btn--active' : ''}`}
            onClick={() => { setSimMode(false); setSimResult(null); }}
          >
            <User size={14} /> Send as Agent
          </button>
          <button
            className={`mode-btn mode-btn--sim ${simMode ? 'mode-btn--active' : ''}`}
            onClick={() => { setSimMode(true); setSimResult(null); }}
          >
            <TestTube size={14} /> Simulate Customer
          </button>
        </div>
        <form className="chat-input" onSubmit={handleSend}>
          <input
            type="text"
            placeholder={simMode ? 'Type as customer to test AI...' : 'Type a message as agent...'}
            value={message}
            onChange={e => setMessage(e.target.value)}
            disabled={sending || simulating}
            className={simMode ? 'chat-input--sim' : ''}
          />
          <Button
            type="submit"
            icon={simMode ? TestTube : Send}
            variant={simMode ? 'secondary' : 'primary'}
            loading={sending || simulating}
            disabled={!message.trim()}
          >
            {simMode ? 'Simulate' : 'Send'}
          </Button>
        </form>
        {simMode && (
          <p className="sim-hint">
            Messages are processed through the full AI pipeline — memory, signals, handoff detection, reply mode ({replyModeInfo.mode}).
            {!botOn && <strong> Bot is currently OFF for this contact. Resume it above to test AI replies.</strong>}
          </p>
        )}
      </div>
    </div>
  );
}
