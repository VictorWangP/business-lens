import React from 'react';
import { it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KnowledgeView } from './KnowledgeView';
import { apiRequest } from '../../services/api';
vi.mock('../../services/api', () => ({apiRequest:vi.fn()}));
it('confirms document removal and reports API errors inside the confirmation dialog', async () => {
  vi.mocked(apiRequest).mockImplementation(async (path,options) => {
    if (options?.method === 'DELETE') throw new Error('文档删除失败');
    if (path.endsWith('/documents')) return [{id:'doc',filename:'销售政策.pdf',status:'ready',file_size:1024,chunk_count:4}];
    return [{id:'kb',name:'销售知识库',document_count:1,created_at:'2026-10-10'}];
  });
  const user=userEvent.setup(); render(<KnowledgeView />);
  await user.click(await screen.findByRole('button',{name:'删除文档 销售政策.pdf'}));
  expect(vi.mocked(apiRequest).mock.calls.some(([,o]) => o?.method === 'DELETE')).toBe(false);
  await user.click(screen.getByRole('button',{name:'取消'}));
  await user.click(screen.getByRole('button',{name:'删除文档 销售政策.pdf'}));
  await user.click(screen.getByRole('button',{name:'确认删除'}));
  expect(await within(screen.getByRole('alertdialog')).findByRole('alert')).toHaveTextContent('文档删除失败');
});
