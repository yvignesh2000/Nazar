import { useState } from 'react';
import { Zap, Eye, EyeOff, AlertCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './Login.css';

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    if (!email || !password) { setError('Email and password required'); return; }
    setLoading(true);
    setError('');
    try {
      await login(email, password);
    } catch (err) {
      setError(err?.message || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <Zap size={28} />
          <span>Nazar</span>
        </div>
        <p className="login-subtitle">Sign in to your workspace</p>

        <form onSubmit={handleSubmit} className="login-form">
          {error && (
            <div className="login-error">
              <AlertCircle size={14} />
              <span>{error}</span>
            </div>
          )}

          <div className="login-field">
            <label>Email</label>
            <input
              type="email"
              placeholder="admin@nazar.app"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoFocus
              autoComplete="email"
            />
          </div>

          <div className="login-field">
            <label>Password</label>
            <div className="login-pw-wrap">
              <input
                type={showPw ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
              />
              <button type="button" className="login-pw-toggle" onClick={() => setShowPw(!showPw)}>
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? <span className="login-spinner" /> : null}
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div className="login-footer">
          <p>Default credentials: <code>admin@nazar.app</code> / <code>changeme123</code></p>
        </div>
      </div>
    </div>
  );
}
