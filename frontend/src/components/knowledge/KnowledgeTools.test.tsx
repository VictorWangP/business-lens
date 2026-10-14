import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KnowledgeTools } from './KnowledgeTools';
import { apiRequest } from '../../services/api';
vi.mock('../../services/api', () => ({apiRequest:vi.fn()}));
const kb = {id:'kb',name:'政策库',description:'审批政策',document_count:2,created_at:'2026-10-10'};
beforeEach(() => { vi.mocked(apiRequest).mockReset(); });

it('shows retrieval evidence and explicit keyword fallback diagnostics', async () => {
  vi.mocked(apiRequest).mockResolvedValue({items:[{chunk_id:'c',content:'折扣需要主管审批',score:0.016,metadata:{filename:'policy.pdf',pages:[3],headings:['审批'],retrieval_sources:['keyword']}}],
    diagnostics:{effective_mode:'keyword',vector_candidates:0,keyword_candidates:1,elapsed_ms:12,warnings:['向量服务不可用；使用关键词检索']}});
  const user=userEvent.setup(); render(<KnowledgeTools kb={kb} refresh={vi.fn()} />);
  await user.click(screen.getByRole('button',{name:'检索调试'}));
  await user.type(screen.getByLabelText('检索问题'),'折扣审批');
  await user.click(screen.getByRole('button',{name:'开始检索'}));
  expect(await screen.findByText('折扣需要主管审批')).toBeInTheDocument();
  expect(screen.getByText('向量服务不可用；使用关键词检索')).toBeInTheDocument();
  expect(screen.getByText(/第 3 页/)).toBeInTheDocument();
  expect(vi.mocked(apiRequest).mock.calls[0][0]).toBe('/knowledge/bases/kb/search');
});

it('submits a full-base rebuild only after confirmation and refreshes state', async () => {
  vi.mocked(apiRequest).mockResolvedValue({batch_id:'batch'});
  const refresh=vi.fn(); const user=userEvent.setup(); render(<KnowledgeTools kb={kb} refresh={refresh} />);
  await user.click(screen.getByRole('button',{name:'全库重建'}));
  expect(apiRequest).not.toHaveBeenCalled();
  const dialog=screen.getByRole('alertdialog');
  expect(within(dialog).getByText(/全部成功后一次切换/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button',{name:'确认'}));
  expect(apiRequest).toHaveBeenCalledWith('/knowledge/bases/kb/reindex',{method:'POST'});
  expect(refresh).toHaveBeenCalledOnce();
});

it('keeps rebuild failures visible in the dialog', async () => {
  vi.mocked(apiRequest).mockRejectedValue(new Error('请等待现有文档处理完成'));
  const user=userEvent.setup(); render(<KnowledgeTools kb={kb} refresh={vi.fn()} />);
  await user.click(screen.getByRole('button',{name:'全库重建'}));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button',{name:'确认'}));
  expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('请等待现有文档处理完成');
});
