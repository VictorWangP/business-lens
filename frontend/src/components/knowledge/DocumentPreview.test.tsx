import { expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentPreview } from './DocumentPreview';
import { apiRequest, downloadDocument } from '../../services/api';
vi.mock('../../services/api', () => ({apiRequest:vi.fn(),downloadDocument:vi.fn()}));
it('previews page/heading evidence, paginates, and downloads with the document identity', async () => {
  vi.mocked(apiRequest).mockImplementation(async path => ({total:21,version:'version123',items:[{id:path,chunk_index:path.includes('offset=20') ? 20 : 0,
    content:path.includes('offset=20') ? '最后一片' : '折扣为百分之五',metadata:{pages:[2],headings:['折扣政策']}}]}));
  const user=userEvent.setup();
  render(<DocumentPreview doc={{id:'doc',kb_id:'kb',filename:'policy.pdf',file_size:100,status:'ready',progress:100,error_msg:'',chunk_count:21,created_at:'',updated_at:''}} onClose={vi.fn()} />);
  expect(await screen.findByText('折扣为百分之五')).toBeInTheDocument();
  expect(screen.getByText(/第 2 页/)).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'下一页'}));
  expect(await screen.findByText('最后一片')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'下载原件'}));
  expect(downloadDocument).toHaveBeenCalledWith('doc','policy.pdf');
});
