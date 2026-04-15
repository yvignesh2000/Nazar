import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { auth as authApi } from '../api/client';

const AuthContext = createContext(null);

const TOKEN_KEY = 'nazar_token';
const USER_KEY = 'nazar_user';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
  });
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [loading, setLoading] = useState(true);

  // On mount, verify stored token is still valid
  useEffect(() => {
    if (!token) { setLoading(false); return; }

    authApi.me(token)
      .then(res => {
        if (res?.user) {
          setUser(res.user);
          localStorage.setItem(USER_KEY, JSON.stringify(res.user));
        } else {
          // Token invalid
          logout();
        }
      })
      .catch(() => {
        // Token expired or invalid — don't force logout for API key users
        // Just clear session state
        setUser(null);
        setToken(null);
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (email, password) => {
    const res = await authApi.login(email, password);
    if (res?.token) {
      setToken(res.token);
      setUser(res.user);
      localStorage.setItem(TOKEN_KEY, res.token);
      localStorage.setItem(USER_KEY, JSON.stringify(res.user));
      return res;
    }
    throw new Error('Login failed');
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const value = {
    user,
    token,
    loading,
    isAuthenticated: !!token || !!user,
    login,
    logout,
    setUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
