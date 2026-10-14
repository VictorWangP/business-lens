import React, { createContext, useContext, useState, useEffect } from 'react';
import { User, AuthResponse } from '../types/auth';
import { apiRequest, getToken, setToken, removeToken } from '../services/api';

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, email?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setTokenState] = useState<string | null>(getToken());
  const [loading, setLoading] = useState<boolean>(true);

  const fetchCurrentUser = async () => {
    const requestToken = getToken();
    try {
      if (requestToken) {
        const u = await apiRequest<User>('/auth/me');
        if (getToken() === requestToken) setUser(current => JSON.stringify(current) === JSON.stringify(u) ? current : u);
      }
    } catch (err) {
      // A temporary connectivity failure on focus must not log out an active session.
      if ((err as {status?:number})?.status === 401 && getToken() === requestToken) {
        removeToken();
        setTokenState(null);
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCurrentUser();

    const handleUnauthorized = () => {
      setUser(null);
      setTokenState(null);
    };
    const handleFeedbackForbidden = () => setUser(current => current ? {...current, role:'user'} : current);
    window.addEventListener('feedback:forbidden', handleFeedbackForbidden);
    window.addEventListener('focus', fetchCurrentUser);
    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => {window.removeEventListener('auth:unauthorized', handleUnauthorized);window.removeEventListener('feedback:forbidden', handleFeedbackForbidden);window.removeEventListener('focus', fetchCurrentUser);};
  }, []);

  const login = async (username: string, password: string) => {
    const res = await apiRequest<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    setToken(res.access_token);
    setTokenState(res.access_token);
    setUser(res.user);
  };

  const register = async (username: string, password: string, email?: string) => {
    const res = await apiRequest<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, email }),
    });
    setToken(res.access_token);
    setTokenState(res.access_token);
    setUser(res.user);
  };

  const logout = () => {
    removeToken();
    setTokenState(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
};
