import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { BookmarkItem } from '../types/chat';
import { apiRequest } from '../services/api';
import { useAuth } from './AuthContext';

interface BookmarkContextType {
  bookmarks: BookmarkItem[];
  loading: boolean;
  isBookmarked: (content: string) => boolean;
  toggleBookmark: (content: string) => Promise<boolean>;
  removeBookmark: (id: string) => Promise<void>;
  refreshBookmarks: () => Promise<void>;
}

const BookmarkContext = createContext<BookmarkContextType | undefined>(undefined);

export const BookmarkProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const [bookmarks, setBookmarks] = useState<BookmarkItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  const fetchBookmarks = useCallback(async () => {
    if (!user) {
      setBookmarks([]);
      return;
    }
    setLoading(true);
    try {
      const data = await apiRequest<BookmarkItem[]>('/chat/bookmarks');
      setBookmarks(data);
    } catch (err) {
      console.error('拉取收藏列表失败', err);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    fetchBookmarks();
  }, [fetchBookmarks]);

  const isBookmarked = useCallback(
    (content: string) => {
      const clean = content.trim();
      return bookmarks.some((b) => b.content.trim() === clean);
    },
    [bookmarks]
  );

  const toggleBookmark = async (content: string): Promise<boolean> => {
    const clean = content.trim();
    if (!clean) return false;
    try {
      const res = await apiRequest<{ bookmarked: boolean; content: string; id: string | null }>(
        '/chat/bookmarks/toggle',
        {
          method: 'POST',
          body: JSON.stringify({ content: clean }),
        }
      );
      if (res.bookmarked && res.id) {
        setBookmarks((prev) => [
          { id: res.id!, content: clean, created_at: new Date().toISOString() },
          ...prev.filter((b) => b.content.trim() !== clean),
        ]);
        return true;
      } else {
        setBookmarks((prev) => prev.filter((b) => b.content.trim() !== clean));
        return false;
      }
    } catch (err) {
      console.error('切换收藏状态失败', err);
      return false;
    }
  };

  const removeBookmark = async (id: string): Promise<void> => {
    try {
      await apiRequest(`/chat/bookmarks/${id}`, { method: 'DELETE' });
      setBookmarks((prev) => prev.filter((b) => b.id !== id));
    } catch (err) {
      console.error('删除收藏失败', err);
    }
  };

  return (
    <BookmarkContext.Provider
      value={{
        bookmarks,
        loading,
        isBookmarked,
        toggleBookmark,
        removeBookmark,
        refreshBookmarks: fetchBookmarks,
      }}
    >
      {children}
    </BookmarkContext.Provider>
  );
};

export const useBookmarks = () => {
  const context = useContext(BookmarkContext);
  if (!context) {
    throw new Error('useBookmarks must be used within BookmarkProvider');
  }
  return context;
};
