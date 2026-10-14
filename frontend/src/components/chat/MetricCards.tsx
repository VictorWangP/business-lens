import { Card } from '../ui/card';
import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { MetricCard } from '../../types/chat';

interface MetricCardsProps {
  metrics: MetricCard[];
}

export const MetricCards: React.FC<MetricCardsProps> = ({ metrics }) => {
  if (!metrics || metrics.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 my-3">
      {metrics.map((item, idx) => (
        <Card
          key={idx}
          className="p-3.5 border-border bg-card text-card-foreground shadow-sm"
        >
          <div className="text-xs text-muted-foreground font-medium mb-1">
            {item.label}
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-xl font-bold tracking-tight text-card-foreground">
              {item.value}
            </span>
            {item.change && (
              <span
                className={`text-xs font-semibold flex items-center space-x-0.5 ${
                  item.trend === 'up'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : item.trend === 'down'
                    ? 'text-rose-600 dark:text-rose-400'
                    : 'text-muted-foreground'
                }`}
              >
                {item.trend === 'up' && <TrendingUp className="w-3.5 h-3.5" />}
                {item.trend === 'down' && <TrendingDown className="w-3.5 h-3.5" />}
                {item.trend === 'neutral' && <Minus className="w-3.5 h-3.5" />}
                <span>{item.change}</span>
              </span>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
};
