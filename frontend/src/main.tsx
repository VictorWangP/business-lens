import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppContent } from './App';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { ConfigProvider } from './context/ConfigContext';
import { BookmarkProvider } from './context/BookmarkContext';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <ThemeProvider>
        <ConfigProvider>
          <BookmarkProvider>
            <AppContent />
          </BookmarkProvider>
        </ConfigProvider>
      </ThemeProvider>
    </AuthProvider>
  </React.StrictMode>
);
