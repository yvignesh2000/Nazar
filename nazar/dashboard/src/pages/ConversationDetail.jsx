import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Send, Bot, User, Play, AlertTriangle, Clock,
  FileEdit, CheckCircle, XCircle, RotateCcw,
  ChevronDown, Sparkles, Pencil, Settings2, TestTube,
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
import { getConversationStatus, statusToBadgeVariant } from '../utils/conversationStatus';
import './ConversationDetail.css';

// "Reply mode" is a SETTING — what should happen when a customer messages?
// (As opposed to the live STATUS, which is what is actually happening right now.)
const REPLY_MODE_OPTIONS = [
  { id: 'auto_ai',    icon: Bot,      label: 'Auto-reply with AI',  desc: 'AI replies to customers automatically.', color: 'var(--color-success-600)' },
  { id: 'ai_draft',   icon: FileEdit, label: 'AI drafts, I approve', desc: 'AI writes a draft. You review before sending.', color: 'var(--color-primary-600)' },
  { id: 'human_only', icon: User,     label: 'I reply manually',     desc: 'AI is paused. You handle this conversation.', color: 'var(--color-orange-600)' },
];

export default function ConversationDetail() {
  const { contactId } = useParams();
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [sendWarning, setSendWarning] = useState(null);

  // Dev tools — hidden by default
  const [showDevTools, setShowDevTools] = useState(false);
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
  const serviceWindow = data?.service_window || { window_open: false, hours_remaining: 0 };

  const currentMode = REPLY_MODE_OPTIONS.find(m => m.id === replyModeInfo.mode) || REPLY_MODE_OPTIONS[0];

  // Live status: what is happening RIGHT NOW (separate from the mode setting).
  const lastMsg = messages.length ? messages[messages.length - 1] : null;
  const liveStatus = getConversationStatus({
    botOn,
    lastDir: lastMsg?.direction,
    lastSender: lastMsg?.sent_by,
    lastTime: lastMsg?.timestamp,
    hasDraft: !!(pendingDraft && pendingDraft.status === 'pending'),
    replyMode: replyModeInfo.mode,
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, simResult, pendingDraft]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (replyModeRef.current && !replyModeRef.current.contains(e.target)) {
        setShowReplyModeMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

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
      setSendWarning(null);
      try {
        const res = await convApi.send(contactId, message.trim());
        setMessage('');
        if (res?.wa_send_error) {
          setSendWarning({ type: 'error', message: res.wa_send_error });
        } else if (res?.window_warning && !res?.whatsapp_sent) {
          setSendWarning({ type: 'warning', message: res.window_warning });
        }
        refetch();
      } catch (err) {
        setSendWarning({ type: 'error', message: err.message || 'Failed to send message' });
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
        <button className="chat-back" onClick={() => navigate('/inbox')}>
          <ArrowLeft size={18} />
        </button>
        <div className="chat-header-avatar">{(contact.name || '?')[0].toUpperCase()}</div>
        <div className="chat-header-info">
          <span className="chat-header-name">{contact.name || 'Unknown'}</span>
          <span className="chat-header-phone">
            {contact.phone}
            {serviceWindow.window_open ? (
              <span className="service-window-badge service-window-badge--open" title={`Reply window open — ${serviceWindow.hours_remaining}h remaining. Free-form messages allowed.`}>
                ● {serviceWindow.hours_remaining}h
              </span>
            ) : (
              <span className="service-window-badge service-window-badge--closed" title="Reply window closed. Only template messages can be sent via WhatsApp.">
                ○ Template only
              </span>
            )}
          </span>
        </div>
        <div className="chat-header-actions">
          {/* LIVE STATUS — what is happening right now */}
          <Badge
            variant={statusToBadgeVariant(liveStatus.tone)}
            size="md"
            dot={liveStatus.animated}
            title={`Live status: ${liveStatus.label}`}
          >
            {liveStatus.label}
          </Badge>

          {!botOn && handoffState?.reason && (
            <Badge variant="orange" size="sm" title={handoffState.reason}>
              <AlertTriangle size={10} /> {handoffState.reason}
            </Badge>
          )}

          {/* MODE SETTING — what SHOULD happen when customers message */}
          <div className="reply-mode-selector" ref={replyModeRef}>
            <button
              className="reply-mode-trigger"
              onClick={() => setShowReplyModeMenu(prev => !prev)}
              disabled={changingMode}
              style={{ '--rm-color': currentMode.color }}
              title="Change how replies are handled for this contact"
            >
              <span className="reply-mode-trigger-label">Mode:</span>
              <currentMode.icon size={14} />
              <span>{currentMode.label}</span>
              {replyModeInfo.source === 'campaign' && (
                <span className="rm-source-badge">Campaign</span>
              )}
              <ChevronDown size={12} className={showReplyModeMenu ? 'rm-chevron-up' : ''} />
            </button>

            {showReplyModeMenu && (
              <div className="reply-mode-dropdown">
                <div className="rm-dropdown-header">When this customer messages, who replies?</div>
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
                      <div className="rm-dropdown-item-text">
                        <span className="rm-dropdown-item-label">{opt.label}</span>
                        <span className="rm-dropdown-item-desc">{opt.desc}</span>
                      </div>
                      {isActive && <CheckCircle size={14} style={{ color: opt.color }} />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Quick toggle — pause/resume the AI for this conversation */}
          <Button
            size="sm"
            variant={botOn ? 'secondary' : 'success'}
            icon={botOn ? User : Play}
            loading={toggling}
            onClick={handleToggleBot}
            title={botOn ? 'Pause AI — you take over this chat' : 'Resume AI — let it reply automatically'}
          >
            {botOn ? 'Take over' : 'Resume AI'}
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>No messages yet</p>
            <p className="chat-empty-hint">Use <strong>Test Mode</strong> below to simulate a customer message and test the AI bot</p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`chat-bubble ${msg.direction === 'inbound' ? 'chat-bubble--in' : 'chat-bubble--out'}`}>
              <div className="chat-bubble-content">
                <MessageContent msg={msg} />
              </div>
              <div className="chat-bubble-meta">
                {msg.sent_by && msg.sent_by !== 'customer' && (
                  <span className="chat-bubble-sender">
                    {msg.sent_by === 'bot' ? <Bot size={10} /> : msg.sent_by === 'bot-approved' ? <><Bot size={10} /><CheckCircle size={8} /></> : <User size={10} />}
                    {msg.sent_by === 'bot-approved' ? 'AI (approved)' : msg.sent_by === 'bot' ? 'AI' : 'You'}
                  </span>
                )}
                {msg.content_type && msg.content_type !== 'text' && (
                  <span className="chat-bubble-type">{msg.content_type}</span>
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
                <span>AI Draft — Review before sending</span>
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
                <Button size="sm" variant="success" icon={Send} loading={approvingDraft} onClick={handleApproveDraft}>
                  {draftEditing ? 'Send Edited' : 'Approve & Send'}
                </Button>
                {!draftEditing ? (
                  <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setDraftEditing(true)}>
                    Edit
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => { setDraftEditing(false); setEditedDraft(pendingDraft.draft); }}>
                    Cancel Edit
                  </Button>
                )}
              </div>
              <div className="draft-actions-right">
                <Button size="sm" variant="ghost" icon={RotateCcw} loading={regenerating} onClick={handleRegenerateDraft}>
                  Regenerate
                </Button>
                <Button size="sm" variant="danger" icon={XCircle} loading={rejectingDraft} onClick={handleRejectDraft}>
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
                  <span>Escalation triggered: <strong>{simResult.handoff_reason}</strong></span>
                </div>
              ) : simResult.mode === 'human' || simResult.mode === 'human_only' ? (
                <div className="sim-result-body">
                  <User size={14} />
                  <span>{"You're replying to this contact. Message saved. No AI response."}</span>
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
                    <span>AI escalated after responding: {simResult.handoff_reason}</span>
                  </div>
                )
              )
            ) : (
              <div className="sim-result-body sim-result-body--error">
                <AlertTriangle size={14} />
                <span>Error: {simResult.error || 'AI failed. Check API keys in Settings.'}</span>
              </div>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Reply window warnings */}
      {!serviceWindow.window_open && (
        <div className="window-warning-banner">
          <Clock size={14} />
          <div className="window-warning-text">
            <strong>Reply window closed</strong> — Free-form messages may be rejected by WhatsApp.
            Use an <strong>approved template</strong> to re-start the conversation, or wait for the customer to message you.
          </div>
        </div>
      )}
      {serviceWindow.window_open && serviceWindow.hours_remaining <= 2 && (
        <div className="window-warning-banner window-warning-banner--soon">
          <Clock size={14} />
          <span>Reply window closing in <strong>{serviceWindow.hours_remaining}h</strong> — consider sending a template for follow-up.</span>
        </div>
      )}

      {/* Send warning/error feedback */}
      {sendWarning && (
        <div className={`send-warning-banner send-warning-banner--${sendWarning.type}`}>
          <AlertTriangle size={14} />
          <span>{sendWarning.message}</span>
          <button onClick={() => setSendWarning(null)}>&times;</button>
        </div>
      )}

      {/* Message Input */}
      <div className="chat-input-wrapper">
        {/* Dev tools toggle — collapsed by default */}
        {!showDevTools && (
          <button className="dev-tools-toggle" onClick={() => setShowDevTools(true)}>
            <Settings2 size={13} />
            <span>Developer Tools</span>
          </button>
        )}

        {showDevTools && (
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
              <TestTube size={14} /> Test Mode
            </button>
            <button className="dev-tools-close" onClick={() => { setShowDevTools(false); setSimMode(false); setSimResult(null); }}>
              Hide
            </button>
          </div>
        )}

        <form className="chat-input" onSubmit={handleSend}>
          <input
            type="text"
            placeholder={simMode ? 'Type as customer to test AI...' : 'Type a message...'}
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
            {simMode ? 'Test' : 'Send'}
          </Button>
        </form>
        {simMode && (
          <p className="sim-hint">
            Messages go through the full AI pipeline — memory, intent detection, escalation, reply mode ({replyModeInfo.mode}).
            {!botOn && <strong> Bot is currently paused for this contact. Turn it on above to test AI replies.</strong>}
          </p>
        )}
      </div>
    </div>
  );
}

function MessageContent({ msg }) {
  const contentType = msg.content_type || 'text';
  const content = msg.content || '';
  const mediaPath = msg.media_path || '';

  if (contentType === 'image' && mediaPath) {
    return (
      <div className="media-content media-image">
        <img src={`/api/media/${encodeURIComponent(mediaPath)}`} alt="Image message" loading="lazy" onClick={() => window.open(`/api/media/${encodeURIComponent(mediaPath)}`, '_blank')} />
        {content && <p className="media-caption">{content}</p>}
      </div>
    );
  }

  if (contentType === 'document' && mediaPath) {
    const filename = mediaPath.split('/').pop() || 'Document';
    return (
      <div className="media-content media-document">
        <a href={`/api/media/${encodeURIComponent(mediaPath)}`} target="_blank" rel="noopener noreferrer" className="media-doc-link">
          <FileEdit size={16} />
          <span>{filename}</span>
        </a>
        {content && <p className="media-caption">{content}</p>}
      </div>
    );
  }

  if (contentType === 'audio' && mediaPath) {
    return (
      <div className="media-content media-audio">
        <audio controls preload="none" src={`/api/media/${encodeURIComponent(mediaPath)}`}>
          Your browser does not support audio.
        </audio>
        {content && <p className="media-caption">{content}</p>}
      </div>
    );
  }

  if (contentType === 'template') {
    return (
      <div className="media-content media-template">
        <div className="template-indicator"><Send size={10} /> Template</div>
        <p>{content}</p>
      </div>
    );
  }

  return <>{content}</>;
}
