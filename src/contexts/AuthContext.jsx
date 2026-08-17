import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext(null);

const AUTH_API_URL = '/api/auth';
const TOKEN_KEY = 'mirai_auth_token';
const USER_KEY = 'mirai_auth_user';

// LOCAL DEV ONLY: `import.meta.env.DEV` is false in production builds, so this
// can never activate on the deployed dashboard. Set VITE_DEV_NO_AUTH=0 in
// .env.development if you want to exercise the real Google SSO flow locally.
const DEV_NO_AUTH = import.meta.env.DEV && import.meta.env.VITE_DEV_NO_AUTH !== '0';
const DEV_USER = { email: 'local@dev', name: 'Local Dev', picture: '', is_admin: true };

export function AuthProvider({ children }) {
  const [user, setUser] = useState(DEV_NO_AUTH ? DEV_USER : null);
  const [loading, setLoading] = useState(!DEV_NO_AUTH);
  const [error, setError] = useState(null);

  // Load user from localStorage on mount
  useEffect(() => {
    if (DEV_NO_AUTH) return; // local dev: no JWT, no verification

    const token = localStorage.getItem(TOKEN_KEY);
    const savedUser = localStorage.getItem(USER_KEY);

    if (token && savedUser) {
      try {
        setUser(JSON.parse(savedUser));
        // Verify token is still valid
        verifyToken(token);
      } catch {
        logout();
      }
    }
    setLoading(false);
  }, []);

  const verifyToken = async (token) => {
    try {
      const response = await fetch(`${AUTH_API_URL}/me`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        // Only drop the session when the token is actually rejected — a 5xx
        // during a backend restart/deploy should not log everyone out.
        if (response.status === 401 || response.status === 403) {
          logout();
        }
        return false;
      }

      const data = await response.json();
      setUser(data.user);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      return true;
    } catch {
      return false;
    }
  };

  const loginWithGoogle = useCallback(async (googleToken) => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${AUTH_API_URL}/google`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ token: googleToken })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Login failed');
      }

      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      setUser(data.user);
      setError(null);

      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    if (DEV_NO_AUTH) return; // local dev session can't be signed out
    setUser(null);
  }, []);

  const getAuthHeader = useCallback(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  }, []);

  const value = {
    user,
    loading,
    error,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin || false,
    loginWithGoogle,
    logout,
    getAuthHeader
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
