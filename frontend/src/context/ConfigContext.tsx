import React, { createContext, useContext, useState, useEffect } from 'react';
import { AppConfigs } from '../types/config';
import { apiRequest } from '../services/api';
import { useAuth } from './AuthContext';

interface ConfigContextType {
  configs: AppConfigs | null;
  loading: boolean;
  refreshConfigs: () => Promise<void>;
  toggleConfig: (key: string) => Promise<void>;
  updateConfig: (key: string, value: any) => Promise<void>;
}

const ConfigContext = createContext<ConfigContextType | undefined>(undefined);

export const ConfigProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const [configs, setConfigs] = useState<AppConfigs | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const fetchConfigs = async () => {
    if (!user) {
      setConfigs(null);
      return;
    }
    setLoading(true);
    try {
      const data = await apiRequest<AppConfigs>('/settings/app-config');
      setConfigs(data);
    } catch (err) {
      console.error('拉取应用配置失败', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfigs();
  }, [user]);

  const toggleConfig = async (key: string) => {
    try {
      await apiRequest(`/settings/app-config/${key}/toggle`, { method: 'PUT' });
      await fetchConfigs();
    } catch (err) {
      console.error('切换配置状态失败', err);
    }
  };

  const updateConfig = async (key: string, value: any) => {
    try {
      await apiRequest(`/settings/app-config/${key}`, {
        method: 'PUT',
        body: JSON.stringify({ config_value: value }),
      });
      await fetchConfigs();
    } catch (err) {
      console.error('更新配置参数失败', err);
      throw err;
    }
  };

  return (
    <ConfigContext.Provider
      value={{
        configs,
        loading,
        refreshConfigs: fetchConfigs,
        toggleConfig,
        updateConfig,
      }}
    >
      {children}
    </ConfigContext.Provider>
  );
};

export const useConfig = () => {
  const context = useContext(ConfigContext);
  if (!context) throw new Error('useConfig must be used within ConfigProvider');
  return context;
};
