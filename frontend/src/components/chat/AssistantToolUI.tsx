import React from 'react';
import { makeAssistantToolUI } from '@assistant-ui/react';
import { ChartViewer } from './ChartViewer';
import { MetricCards } from './MetricCards';
import { ChartConfig, MetricCard } from '../../types/chat';

/**
 * 官方 assistant-ui Generative UI 工具集成：
 * 当大模型或后端触发工具渲染时，自动挂载为 assistant-ui 原生工具卡片
 */
export const ChartToolUI = makeAssistantToolUI<{ chart: ChartConfig }, any>({
  toolName: 'render_chart',
  render: ({ args }) => {
    if (!args?.chart) return null;
    return <ChartViewer chart={args.chart} />;
  },
});

export const MetricToolUI = makeAssistantToolUI<{ metrics: MetricCard[] }, any>({
  toolName: 'render_metrics',
  render: ({ args }) => {
    if (!args?.metrics) return null;
    return <MetricCards metrics={args.metrics} />;
  },
});
