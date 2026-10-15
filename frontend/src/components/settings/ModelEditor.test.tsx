import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ModelEditor } from './ModelEditor';
import { ConfigModals } from './ConfigModals';
import { apiRequest } from '../../services/api';
import type { AppConfigs } from '../../types/config';

vi.mock('../../services/api', () => ({ apiRequest: vi.fn() }));
const probe = vi.mocked(apiRequest);
beforeEach(() => { probe.mockReset(); probe.mockResolvedValue({models:['model-a','model-b'], message:'连接成功'}); });
const existing = {id:'old-id', name:'Original', type:'llm' as const, provider:'Provider', base_url:'https://provider.test/v1', api_key:'********'};
const configs = {
  welcome_setting:{questions:[]}, model_setting:{default_model:'old-id', default_embedding_model:'embed', temperature:0.2,
    available_models:[existing, {id:'embed', name:'Embed', type:'embedding'}]}, frequent_questions:{is_enabled:true,threshold:3},
} as AppConfigs;

describe('shadcn model configuration', () => {
  it('preserves and edits explicit provider capacity', async () => {
    const user = userEvent.setup(); const confirm = vi.fn();
    const configured = {...existing, context_window:262144, max_input_tokens:240000, max_output_tokens:8192};
    render(<ModelEditor model={configured} models={[configured]} onClose={vi.fn()} onConfirm={confirm} />);
    expect(screen.getByLabelText('上下文窗口')).toHaveValue(262144);
    await user.clear(screen.getByLabelText('最大输入 Token'));
    await user.type(screen.getByLabelText('最大输入 Token'), '200000');
    await waitFor(() => expect(screen.getByRole('button', {name:'确认修改'})).toBeEnabled(), {timeout:3000});
    await user.click(screen.getByRole('button', {name:'确认修改'}));
    expect(confirm).toHaveBeenCalledWith([expect.objectContaining({context_window:262144, max_input_tokens:200000, max_output_tokens:8192})], 'old-id');
  });
  it('starts empty and requires user configuration before connecting or adding', async () => {
    const user = userEvent.setup(); const confirm = vi.fn();
    render(<ModelEditor models={[]} onClose={vi.fn()} onConfirm={confirm} />);
    expect(screen.getByLabelText('API Base URL')).toHaveValue('');
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    expect(screen.getByLabelText('模型 ID（支持手动填写）')).toHaveValue('');
    expect(screen.getByRole('button', {name:'测试连接'})).toBeDisabled();
    await user.click(screen.getByRole('button', {name:'确认添加'}));
    expect(confirm).not.toHaveBeenCalled();
    expect(probe).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('API Key');
  });

  it('discovers models, selects from the dropdown, tests connection and imports a provider in one operation', async () => {
    const user = userEvent.setup(); const confirm = vi.fn();
    render(<ModelEditor models={[]} onClose={vi.fn()} onConfirm={confirm} />);
    await user.clear(screen.getByLabelText('API Base URL')); await user.type(screen.getByLabelText('API Base URL'), 'https://provider.test/v1');
    await user.type(screen.getByLabelText('API Key'), 'provider-secret');
    const catalog = await screen.findByRole('combobox', {name:'供应商模型列表'}, {timeout:3000});
    await user.click(catalog); await user.click(await screen.findByRole('option', {name:'model-b'}));
    expect(screen.getByLabelText('模型 ID（支持手动填写）')).toHaveValue('model-b');
    await user.click(screen.getByRole('button', {name:'测试连接'}));
    await waitFor(() => expect(probe).toHaveBeenCalledWith('/settings/model-provider/test', expect.anything()), {timeout:3000});
    await user.click(await screen.findByRole('checkbox'));
    await user.click(screen.getByRole('button', {name:'确认添加'}));
    expect(confirm).toHaveBeenCalledWith([
      expect.objectContaining({id:'model-b', api_key:'provider-secret'}), expect.objectContaining({id:'model-a', api_key:'provider-secret'}),
    ], undefined);
  });

  it('edits a model in a nested dialog and preserves its key and default selection after renaming', async () => {
    const user = userEvent.setup(); const save = vi.fn().mockResolvedValue(undefined);
    render(<ConfigModals type="model" configs={configs} onClose={vi.fn()} onSave={save} />);
    await user.click(screen.getByRole('button', {name:'编辑模型 Original'}));
    const editor = screen.getByRole('dialog', {name:'编辑模型'});
    await user.clear(within(editor).getByLabelText('模型 ID（支持手动填写）'));
    await user.type(within(editor).getByLabelText('模型 ID（支持手动填写）'), 'renamed-id');
    await waitFor(() => expect(within(editor).getByRole('button', {name:'确认修改'})).toBeEnabled(), {timeout:3000});
    await user.click(within(editor).getByRole('button', {name:'确认修改'}));
    await user.click(screen.getByRole('button', {name:'保存'}));
    expect(save).toHaveBeenCalledWith('model_setting', expect.objectContaining({default_model:'renamed-id', available_models:expect.arrayContaining([
      expect.objectContaining({id:'renamed-id', api_key:'********', credential_model_id:'old-id'}),
    ])}));
  });

  it('keeps the form and shows failures when saving fails', async () => {
    const user = userEvent.setup();
    render(<ConfigModals type="model" configs={configs} onClose={vi.fn()} onSave={vi.fn().mockRejectedValue(new Error('保存失败，请重试'))} />);
    await user.click(screen.getByRole('button', {name:'保存'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存失败，请重试');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('falls back to manual IDs and aborts pending discovery when the dialog closes', async () => {
    probe.mockRejectedValue(new Error('供应商不支持模型列表'));
    const user = userEvent.setup(); const confirm = vi.fn(); const close = vi.fn();
    const view = render(<ModelEditor model={existing} models={[existing]} onClose={close} onConfirm={confirm} />);
    expect(await screen.findByRole('alert', {}, {timeout:3000})).toHaveTextContent('不支持模型列表');
    await user.clear(screen.getByLabelText('模型 ID（支持手动填写）')); await user.type(screen.getByLabelText('模型 ID（支持手动填写）'), 'manual-id');
    await user.click(screen.getByRole('button', {name:'确认修改'}));
    expect(confirm).toHaveBeenCalledWith([expect.objectContaining({id:'manual-id'})], 'old-id');
    const signal = probe.mock.calls[0][1]?.signal;
    await user.keyboard('{Escape}'); expect(close).toHaveBeenCalled();
    view.unmount(); expect(signal?.aborted).toBe(true);
  });
});

it('only saves positive integer frequent thresholds and removes manual question editing', async () => {
  const user=userEvent.setup(); const save=vi.fn();
  render(<ConfigModals type="frequent" configs={configs} onClose={vi.fn()} onSave={save} />);
  expect(screen.queryByLabelText('新的常问问题')).not.toBeInTheDocument();
  const input=screen.getByLabelText('常问问题展示次数阈值');
  await user.clear(input); await user.type(input,'1.5');
  await user.click(screen.getByRole('button',{name:'保存'}));
  expect(await screen.findByText('阈值必须为正整数')).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
  await user.clear(input); await user.type(input,'12');
  await user.click(screen.getByRole('button',{name:'保存'}));
  expect(save).toHaveBeenCalledWith('frequent_questions',{threshold:12});
});
