import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnalysisProcess } from './AnalysisProcess';
import type { Message } from '../../types/chat';

const base: Message = {id:'a',conversation_id:'c',role:'assistant',content:'',created_at:'2026-10-14T00:00:00Z'};
describe('analysis execution details', () => {
  it('shows failed attempts and unfinished operations after a run stops', async () => {
    render(<AnalysisProcess message={{...base,tool_calls:{status:'cancelled',execution_events:[
      {type:'tool_start',name:'execute_readonly_sql',tool_id:'one',args:{sql:'SELECT invalid FROM dataset'}},
      {type:'tool_end',tool_id:'one',result:{status:'failed',error:'字段不存在'}},
      {type:'tool_start',name:'get_business_schema',tool_id:'two',args:{source_id:'orders'}},
    ]}}} isWorking={false} />);
    await userEvent.click(screen.getByRole('button',{name:/分析过程/}));
    expect(screen.getByText('失败原因：字段不存在')).toBeVisible();
    expect(screen.getByText('失败')).toBeVisible();
    expect(screen.getByText('未完成')).toBeVisible();
    expect(screen.getByText('数据集 ID：orders')).toBeVisible();
  });
  it('shows empty and truncated result summaries without treating them as errors', async () => {
    render(<AnalysisProcess message={{...base,tool_calls:{execution_events:[
      {type:'tool_start',name:'execute_readonly_sql',tool_id:'one'},
      {type:'tool_end',tool_id:'one',result:{status:'completed',source_name:'订单',row_count:0,truncated:true}},
    ]}}} isWorking={false} />);
    await userEvent.click(screen.getByRole('button',{name:/分析过程/}));
    expect(screen.getByText('查询结果：返回 0 行（结果已截断，仅展示部分数据）')).toBeVisible();
    expect(screen.getByText('已完成')).toBeVisible();
  });
});
