import React from 'react';
import { DataSourcesPanel } from './DataSourcesPanel';

export const DataSourcesView: React.FC = () => (
  <div className="min-h-full bg-background text-foreground p-8 max-w-7xl mx-auto space-y-6">
    <div>
      <div className="text-xs font-semibold text-muted-foreground tracking-wider">
        数据管理 / 业务数据
      </div>
      <h2 className="text-xl font-bold text-foreground mt-1">业务数据管理</h2>
      <p className="text-sm text-muted-foreground mt-2">导入 CSV / Excel 数据，查看数据集并维护业务指标口径。</p>
    </div>
    <DataSourcesPanel />
  </div>
);
