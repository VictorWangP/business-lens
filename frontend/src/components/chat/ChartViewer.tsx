import React, { useEffect, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { BarChart3, LineChart as LineIcon, PieChart as PieIcon } from 'lucide-react';
import { ChartConfig } from '../../types/chat';
import { Button } from '../ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';

type ChartType = 'bar' | 'line' | 'pie';

// Keep large amounts inside the axis gutter (e.g. 4,000,000,000 → 40亿).
const axisNumberFormat = new Intl.NumberFormat('zh-CN', {
  notation: 'compact', maximumSignificantDigits: 4,
});
const tooltipNumberFormat = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 20,
});
const formatAxisTick = (value: number) => axisNumberFormat.format(value);
const formatTooltipValue = (value: number | string | (number | string)[]) =>
  typeof value === 'number' ? tooltipNumberFormat.format(value) : value;

export const ChartViewer: React.FC<{ chart: ChartConfig }> = ({ chart }) => {
  const pieKey = chart.y_keys[0];
  const pieValues = chart.data.map(row => row[pieKey]);
  const canPie = pieValues.length > 0 && pieValues.every(v => typeof v === 'number' && Number.isFinite(v) && v >= 0)
    && pieValues.reduce<number>((sum, v) => sum + (typeof v === 'number' ? v : 0), 0) > 0;
  const preferred: ChartType = chart.type === 'line' ? 'line' : chart.type === 'pie' && canPie ? 'pie' : 'bar';
  const [chartType, setChartType] = useState<ChartType>(preferred);
  useEffect(() => { setChartType(preferred); }, [preferred]);
  const activeType = chartType === 'pie' && !canPie ? 'bar' : chartType;
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#64748b'];

  const tooltipStyle: React.CSSProperties = {
    backgroundColor: 'hsl(var(--popover))',
    borderColor: 'hsl(var(--border))',
    borderRadius: 'calc(var(--radius) - 2px)',
    color: 'hsl(var(--popover-foreground))',
    boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
  };

  const axes = <>
    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
    <XAxis dataKey={chart.x_key} stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} />
    <YAxis width={80} tickFormatter={formatAxisTick} stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} />
    <Tooltip contentStyle={tooltipStyle} formatter={formatTooltipValue} />
    <Legend wrapperStyle={{ fontSize: 12, color: 'hsl(var(--muted-foreground))' }} />
  </>;

  return (
    <Card className="my-4 border-border bg-card text-card-foreground shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2 space-y-0 gap-2">
        <CardTitle className="text-sm font-semibold tracking-normal text-card-foreground">
          {chart.title}
        </CardTitle>
        <div className="flex items-center space-x-1 p-0.5 rounded-lg bg-muted">
          {([{type:'bar', label:'柱状图', Icon:BarChart3}, {type:'line', label:'折线图', Icon:LineIcon}, {type:'pie', label:'饼图', Icon:PieIcon}] as const).map(({type,label,Icon}) =>
            <Button
              variant="ghost"
              size="icon"
              key={type}
              onClick={() => setChartType(type)}
              disabled={type === 'pie' && !canPie}
              aria-label={`切换为${label}`}
              aria-pressed={activeType === type}
              title={type === 'pie' && !canPie ? '饼图需要非负数值，且合计大于零' : `切换为${label}`}
              className={`h-7 w-7 p-1.5 rounded-md text-xs transition disabled:opacity-30 ${
                activeType === type
                  ? 'bg-background text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-4 pt-2">
        {activeType === 'pie' && (
          <p className="text-xs text-muted-foreground mb-2">
            占比指标：{pieKey}；百分比按当前查询返回的类别合计计算。
          </p>
        )}
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            {activeType === 'pie' ? (
              <PieChart>
                <Pie data={chart.data} dataKey={pieKey} nameKey={chart.x_key} cx="50%" cy="45%" outerRadius="70%"
                  label={({percent}) => `${((percent || 0)*100).toFixed(1)}%`}>
                  {chart.data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} formatter={formatTooltipValue} />
                <Legend wrapperStyle={{ fontSize: 12, color: 'hsl(var(--muted-foreground))' }} />
              </PieChart>
            ) : activeType === 'line' ? (
              <LineChart data={chart.data} margin={{top:10,right:10,left:0,bottom:0}}>
                {axes}
                {chart.y_keys.map((key,i) => (
                  <Line key={key} type="linear" dataKey={key} stroke={colors[i % colors.length]}
                    strokeWidth={2.5} dot={{r:3}} activeDot={{r:5}} connectNulls={false} />
                ))}
              </LineChart>
            ) : (
              <BarChart data={chart.data} margin={{top:10,right:10,left:0,bottom:0}}>
                {axes}
                {chart.y_keys.map((key,i) => (
                  <Bar key={key} dataKey={key} fill={colors[i % colors.length]} radius={[4,4,0,0]} />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};
