import { useEffect, useState } from 'react';
import { apiRequest } from '../services/api';

export interface FrequentQuestion {
  id: string;
  question: string;
  count: number;
  last_asked_at: string;
}

export function useFrequentQuestions(sourceIds: string[], enabled: boolean, threshold: number, isLoading: boolean, workspaceId?: string, workspaceVersion?: number) {
  const scope = JSON.stringify([Array.from(new Set(sourceIds)).sort(), workspaceId, workspaceVersion]);
  const [result, setResult] = useState<{scope: string; items: FrequentQuestion[]}>({scope: '', items: []});
  useEffect(() => {
    if (!enabled) { setResult({scope, items: []}); return; }
    const [sources] = JSON.parse(scope) as string[][];
    const params = new URLSearchParams();
    if (workspaceId) params.set('workspace_id', workspaceId);
    else {
      sources.forEach(id => params.append('source_ids', id));
    }
    let active = true;
    let sequence = 0;
    const controller = new AbortController();
    async function refresh() {
      const current = ++sequence;
      try {
        const items = await apiRequest<FrequentQuestion[]>(`/frequent-questions?${params}`, {signal: controller.signal});
        if (active && current === sequence) setResult({scope, items});
      } catch {
        if (active && current === sequence) setResult({scope, items: []});
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [scope, enabled, threshold, isLoading]);
  return enabled && result.scope === scope ? result.items : [];
}
