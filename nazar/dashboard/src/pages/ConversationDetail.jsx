import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Send, Bot, User, HandMetal, Play, AlertTriangle } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { conversations as convApi, handoffs as handoffApi } from '../api/client';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Spinner from '../components/ui/Spinner';
import { format } from 'date-fns';
import './ConversationDetail.css';

export default function ConversationDetail() {
  const { contactId } = useParams();
  const navigate = useNavigate();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [toggling, setToggling] = useState(false);
  const messagesEndRef = useRef(null);

  const { data, loading, refetch } = useApi(
    () => convApi.get(contactId), [contactId]
  );

  const contact = data?.contact || {};
  const messages = data?.messages || [];
  const botOn = data?.bot_mode !== false;
  const handoffState = data?.handoff_state || null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  async function handleSend(e) {
    e.preventDefault();
    if (!message.trim() || sending) return;
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

  async function handleToggleBot() {
    setToggling(true);
    try {
      if (!botOn) {
        // Resume bot
        await handoffApi.resume(contactId, 'Resumed from chat');
      } else {
        // Turn off bot (handover to human)
        await convApi.handover(contactId, false);
      }
      refetch();
    } catch (err) {
      console.error('Toggle failed:', err);
    } finally {
      setToggling(false);
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
          <div className="chat-empty">No messages yet</div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`chat-bubble ${msg.direction === 'inbound' ? 'chat-bubble--in' : 'chat-bubble--out'}`}>
              <div className="chat-bubble-content">{msg.text || msg.message || ''}</div>
              <div className="chat-bubble-meta">
                {msg.sent_by && msg.sent_by !== 'customer' && (
                  <span className="chat-bubble-sender">
                    {msg.sent_by === 'bot' ? <Bot size={10} /> : <User size={10} />}
                    {msg.sent_by}
                  </span>
                )}
                <span className="chat-bubble-time">
                  {msg.timestamp ? format(new Date(msg.timestamp), 'h:mm a') : ''}
                </span>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form className="chat-input" onSubmit={handleSend}>
        <input
          type="text"
          placeholder="Type a message..."
          value={message}
          onChange={e => setMessage(e.target.value)}
          disabled={sending}
        />
        <Button type="submit" icon={Send} loading={sending} disabled={!message.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}
