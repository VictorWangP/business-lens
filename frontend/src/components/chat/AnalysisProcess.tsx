import { useState } from 'react';
import { CheckCircle2, ChevronRight, CircleAlert, Cpu, Loader2 } from 'lucide-react';
import { Message } from '../../types/chat';
import { executionEvents } from '../../lib/chat-runtime';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';

const actions: Record<string, [string, string]> = {
  list_available_resources: ['确认可用资源', '确认本次业务空间中可查询的数据集和指标。'],
  get_business_schema: ['读取业务字段', '核对数据结构和授权视图，作为生成查询的依据。'],
  execute_readonly_sql: ['查询业务数据', '按下方 SQL 的筛选、分组和聚合条件读取业务数据。'],
  query_metrics: ['查询业务指标', '使用已定义的指标口径查询指定期间，开始日期包含，结束日期不包含。'],
  read_query_result: ['读取历史查询', '读取已保存的精确查询结果，作为后续分析依据。'],
  read_tool_result: ['读取已保存结果', '按需分段读取已保存的业务资料，补充本次分析依据。'],
  ask_clarification: ['确认业务条件', '关键业务条件不足，等待补充后继续执行。'],
};
const statuses: Record<string, string> = {queued:'排队中',running:'运行中',cancel_requested:'正在停止',
  completed:'完成',partial:'部分完成',failed:'执行失败',cancelled:'已停止',paused:'等待补充'};
const fields: Record<string, string> = {source_id:'数据集 ID',metric_id:'指标 ID',start_date:'开始日期（含）',end_date:'结束日期（不含）',
  query_id:'查询引用',question:'待确认条件'};

export function AnalysisProcess({message, isWorking}: {message: Message; isWorking: boolean}) {
  const [open, setOpen] = useState(false);
  const events = executionEvents(message);
  const status = message.tool_calls?.status || (isWorking ? 'running' : '');
  const queries = message.tool_calls?.presentation?.queries || [];
  const sources = new Map<string, string>();
  events.forEach(event => {
    event.result?.sources?.forEach(source => sources.set(source.id, source.name));
    if (event.result?.source_id && event.result.source_name) sources.set(event.result.source_id, event.result.source_name);
  });
  const steps = events.filter(event => event.type === 'tool_start');
  if (!isWorking && !events.length && !queries.length && !status) return null;
  return <Collapsible open={open} onOpenChange={setOpen} className="mb-3 text-xs">
    <CollapsibleTrigger className="flex w-full items-center justify-between rounded-xl bg-blue-50/70 hover:bg-blue-100/70 dark:bg-muted/40 dark:hover:bg-muted/60 px-3.5 py-2.5 text-left transition-colors">
      <div className="flex items-center gap-1.5 font-medium text-blue-600 dark:text-blue-400">
        <Cpu aria-hidden="true" className="h-4 w-4 shrink-0" />
        <span>分析过程{status ? ` · ${statuses[status] || status}` : ''}</span>
        <ChevronRight aria-hidden="true" className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
      </div>
      <span className="text-xs text-muted-foreground select-none">{open ? '点击收起' : '点击展开'}</span>
    </CollapsibleTrigger>
    <CollapsibleContent className="mt-2 space-y-3 text-muted-foreground">
      <p>展示实际工具调用、查询依据与处理说明。</p>
      {!steps.length && <p>{isWorking ? '正在准备分析步骤…' : '此记录未保存工具步骤。'}</p>}
      <ol className="space-y-3">
        {steps.map((step, index) => {
          const end = events.find(event => event.type === 'tool_end' && event.tool_id === step.tool_id);
          const result = end?.result;
          const args = step.args || {};
          const failed = result?.status === 'failed';
          const [label, explanation] = actions[step.name || ''] || [step.name || '执行工具', '执行工具获取业务依据。'];
          const sourceName = result?.source_name || sources.get(String(args.source_id || ''));
          const sql = result?.sql || (typeof args.sql === 'string' ? args.sql : '');
          return <li key={step.tool_id || index} className="min-w-0 rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-center gap-2 font-medium text-foreground">
              {failed ? <CircleAlert aria-hidden="true" className="h-3.5 w-3.5 text-destructive" /> : end ? <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-emerald-600" /> : isWorking ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <CircleAlert aria-hidden="true" className="h-3.5 w-3.5" />}
              <span>{index + 1}. {label}</span><span className="ml-auto shrink-0 text-muted-foreground">{failed ? '失败' : end ? '已完成' : isWorking ? '执行中' : status === 'paused' ? '等待补充' : '未完成'}</span>
            </div>
            <p className="mt-2">处理说明：{explanation}</p>
            {sourceName && <p className="mt-1 break-words">业务数据集：{sourceName}</p>}
            {Object.entries(args).filter(([key, value]) => key in fields && (typeof value === 'string' || typeof value === 'number') && !(key === 'source_id' && sourceName)).map(([key, value]) => <p key={key} className="mt-1 break-words">{fields[key]}：{String(value)}</p>)}
            {result?.sources?.length ? <p className="mt-1 break-words">可用数据集：{result.sources.map(source => source.name).join('、')}</p> : null}
            {result?.metric && <p className="mt-1">指标：{result.metric}{result.definition ? ` · ${result.definition}` : ''}</p>}
            {sql && <div className="mt-2"><p className="mb-1 font-medium">{result?.sql ? '执行 SQL' : '待执行 SQL'}</p><pre className="max-h-72 max-w-full overflow-auto rounded-md border border-border bg-background p-3 text-foreground"><code>{sql}</code></pre></div>}
            {result?.row_count !== undefined && <p className="mt-2">查询结果：返回 {result.row_count} 行{result.truncated ? '（结果已截断，仅展示部分数据）' : ''}</p>}
            {result?.error && <p role="alert" className="mt-2 whitespace-pre-wrap break-words text-destructive">失败原因：{result.error}</p>}
          </li>;
        })}
      </ol>
      {!steps.length && queries.map((query, index) => <div key={query.query_id || index} className="rounded-lg border border-border p-3">
        <p>业务数据集：{query.source_name}</p>
        {query.sql && <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-3"><code>{query.sql}</code></pre>}
        <p className="mt-2">查询结果：返回 {query.rows?.length || 0} 行{query.truncated ? '（结果已截断）' : ''}</p>
      </div>)}
      {status && <p>执行状态：{statuses[status] || status}</p>}
    </CollapsibleContent>
  </Collapsible>;
}
