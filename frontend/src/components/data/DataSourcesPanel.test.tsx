import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DataSourcesPanel } from './DataSourcesPanel';
import { apiRequest } from '../../services/api';
vi.mock('../../services/api', () => ({apiRequest:vi.fn()}));
const source = {id:'sales',name:'月度销售',kind:'csv',description:'收入与毛利',allowed_views:['dataset']};
beforeEach(() => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === '/data-sources') return [source];
    if (path.endsWith('/test')) return {columns:[{table_name:'dataset',column_name:'revenue',data_type:'DECIMAL'}]};
    if (path.endsWith('/query')) return {rows:[{month:'2026-10',revenue:'1234567890.12'}],truncated:true};
    return undefined;
  });
});
describe('business data controls', () => {
  it('requires confirmation before deleting and allows cancellation without a request', async () => {
    const user=userEvent.setup(); render(<DataSourcesPanel />);
    await user.click(await screen.findByRole('button',{name:'移除数据集'}));
    expect(screen.getByRole('alertdialog')).toHaveTextContent('月度销售');
    expect(vi.mocked(apiRequest).mock.calls.some(([,o]) => o?.method === 'DELETE')).toBe(false);
    await user.click(screen.getByRole('button',{name:'取消'}));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'移除数据集'}));
    await user.click(screen.getByRole('button',{name:'确认移除'}));
    expect(apiRequest).toHaveBeenCalledWith('/data-sources/sales',{method:'DELETE'});
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });
  it('keeps the deletion dialog open with a readable error when removal fails', async () => {
    const user=userEvent.setup(); render(<DataSourcesPanel />);
    await user.click(await screen.findByRole('button',{name:'移除数据集'}));
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error('移除失败，请重试'));
    await user.click(screen.getByRole('button',{name:'确认移除'}));
    expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('移除失败，请重试');
  });
  it('renders queried amounts as table cells without changing precision or hiding truncation', async () => {
    const user=userEvent.setup(); render(<DataSourcesPanel />);
    await user.click(await screen.findByRole('button',{name:'查看数据'}));
    await user.click(await screen.findByRole('button',{name:'执行查询'}));
    expect(await screen.findByRole('table',{name:'业务查询结果'})).toHaveTextContent('1234567890.12');
    expect(screen.getByText('返回 1 行（已截断）')).toBeInTheDocument();
  });
});
