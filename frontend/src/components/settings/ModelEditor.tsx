import React, { useEffect, useState } from 'react';
import { Loader2, Eye, EyeOff } from 'lucide-react';
import { ModelItem } from '../../types/config';
import { apiRequest } from '../../services/api';
import { Alert, AlertDescription } from '../ui/alert';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Checkbox } from '../ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem, SelectGroup, SelectLabel } from '../ui/select';

export function ModelEditor({ model, models, onClose, onConfirm }: {
  model?: ModelItem; models: ModelItem[]; onClose: () => void;
  onConfirm: (items: ModelItem[], previousId?: string) => void;
}) {
  const [provider, setProvider] = useState(model?.provider || '');
  const [baseUrl, setBaseUrl] = useState(model?.base_url || '');
  const [apiKey, setApiKey] = useState(model?.api_key || '');
  const [credentialId, setCredentialId] = useState(model?.credential_model_id || model?.id);
  const [kind, setKind] = useState<'llm' | 'embedding'>(model?.type || 'llm');
  const [id, setId] = useState(model?.id || '');
  const [name, setName] = useState(model?.name || '');
  const [description, setDescription] = useState(model?.description || '');
  const [contextWindow, setContextWindow] = useState(model?.context_window?.toString() || '');
  const [maxInput, setMaxInput] = useState(model?.max_input_tokens?.toString() || '');
  const [maxOutput, setMaxOutput] = useState(model?.max_output_tokens?.toString() || '');
  const [showKey, setShowKey] = useState(false);
  const [catalog, setCatalog] = useState<string[]>([]);
  const [addAll, setAddAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [request, setRequest] = useState({ version: 0, test: false });

  useEffect(() => {
    const controller = new AbortController();
    setCatalog([]); setNotice(''); setError(''); setBusy(false); setAddAll(false);
    if (!baseUrl.trim() || !apiKey.trim()) return;
    setBusy(true);
    const timer = window.setTimeout(async () => {
      try {
        const result = await apiRequest<{ models: string[]; message: string }>(
          `/settings/model-provider/${request.test ? 'test' : 'models'}`, {
            method: 'POST', signal: controller.signal,
            body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey.trim(), credential_model_id: credentialId }),
          });
        if (controller.signal.aborted) return;
        setCatalog(result.models);
        setId(current => current || result.models[0] || '');
        setNotice(request.test ? `${result.message}。此测试验证连接和模型列表权限。` : `已获取 ${result.models.length} 个模型，可下拉选择或批量添加。`);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : '获取模型失败，可手动填写模型 ID');
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, 800);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [baseUrl, apiKey, credentialId, request]);

  function confirm() {
    setError('');
    if (kind === 'llm' && [[contextWindow, 8192], [maxInput, 1024], [maxOutput, 256]].some(([value, minimum]) =>
      value !== '' && (!Number.isSafeInteger(Number(value)) || Number(value) < Number(minimum)))) {
      setError('模型容量必须为正整数：上下文至少 8192，输入至少 1024，输出至少 256'); return;
    }
    const ids = addAll && !model
      ? catalog.includes(id.trim()) ? [id.trim(), ...catalog.filter(value => value !== id.trim())] : catalog
      : [id.trim()];
    if (!baseUrl.trim() || !apiKey.trim() || !ids.length || ids.some(value => !value)) {
      setError('请填写 Base URL、API Key 并选择或输入模型 ID'); return;
    }
    if (ids.some(value => models.some(existing => existing.id === value && existing.id !== model?.id
      && (!addAll || existing.base_url?.replace(/\/$/, '') !== baseUrl.trim().replace(/\/$/, ''))))) {
      setError('模型 ID 已存在，请编辑已有模型，或选择其他 ID'); return;
    }
    const items = ids.map(value => ({
      id: value, name: value === id.trim() ? name.trim() || value : value,
      type: kind, provider: provider.trim() || '通用供应商', base_url: baseUrl.trim(),
      api_key: apiKey.trim() || undefined, credential_model_id: credentialId,
      description: description.trim() || undefined,
      ...(kind === 'llm' && value === id.trim() ? {
        context_window: contextWindow ? Number(contextWindow) : null,
        max_input_tokens: maxInput ? Number(maxInput) : null,
        max_output_tokens: maxOutput ? Number(maxOutput) : null,
      } : {}),
    }));
    onConfirm(items, model?.id);
  }

  const canConnect = !!baseUrl.trim() && !!apiKey.trim();
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-w-lg max-h-[90dvh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{model ? '编辑模型' : '添加供应商模型'}</DialogTitle>
        <DialogDescription>配置供应商连接，选择对话或嵌入模型；确认后请在主弹窗保存。</DialogDescription>
      </DialogHeader>
      {!model && <div className="space-y-2">
        <Label htmlFor="provider-preset">已配置供应商</Label>
        <Select onValueChange={value => {
          const existing = models.find(m => `saved:${m.id}` === value);
          if (existing) {
            setProvider(existing.provider || '通用供应商'); setBaseUrl(existing.base_url || '');
            setApiKey(existing.api_key || ''); setCredentialId(existing.credential_model_id || existing.id);
          }
          setId(''); setName('');
        }}>
          <SelectTrigger id="provider-preset"><SelectValue placeholder="选择供应商，或填写下方信息" /></SelectTrigger>
          <SelectContent>
            <SelectGroup><SelectLabel>已配置供应商</SelectLabel>
              {models.filter((m, index, all) => m.api_key && all.findIndex(x => x.base_url === m.base_url && x.api_key) === index)
                .map(m => <SelectItem key={m.id} value={`saved:${m.id}`}>{m.provider} · {m.base_url}</SelectItem>)}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>}
      <div className="space-y-2"><Label htmlFor="model-provider">供应商名称</Label>
        <Input id="model-provider" value={provider} onChange={e => setProvider(e.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="model-base-url">API Base URL</Label>
        <Input id="model-base-url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" /></div>
      <div className="space-y-2"><Label htmlFor="model-api-key">API Key</Label>
        <div className="flex gap-2">
          <Input id="model-api-key" autoComplete="off" type={showKey ? 'text' : 'password'} value={apiKey} onChange={e => setApiKey(e.target.value)} aria-describedby="model-key-help" />
          <Button variant="outline" size="icon" aria-label={showKey ? '隐藏 API Key' : '显示 API Key'} onClick={() => setShowKey(!showKey)}>{showKey ? <EyeOff /> : <Eye />}</Button>
        </div>
        <p id="model-key-help" className="text-xs text-muted-foreground">请填写服务使用的 API Key；******** 表示保留已保存密钥。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={busy || !canConnect} onClick={() => setRequest(r => ({ version: r.version + 1, test: false }))}>刷新模型列表</Button>
        <Button variant="outline" size="sm" disabled={busy || !canConnect} onClick={() => setRequest(r => ({ version: r.version + 1, test: true }))}>测试连接</Button>
      </div>
      {busy && <div role="status" className="flex gap-2 items-center text-sm text-primary"><Loader2 className="w-4 h-4 animate-spin" />正在连接供应商并获取模型…</div>}
      {notice && <Alert role="status"><AlertDescription>{notice}</AlertDescription></Alert>}
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="space-y-2"><Label htmlFor="model-kind">模型类型</Label>
        <Select value={kind} onValueChange={value => setKind(value as 'llm' | 'embedding')}>
          <SelectTrigger id="model-kind"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="llm">LLM 对话模型</SelectItem><SelectItem value="embedding">Embedding 向量模型</SelectItem></SelectContent>
        </Select>
      </div>
      {catalog.length > 0 && <div className="space-y-2"><Label htmlFor="model-catalog">供应商模型列表</Label>
        <Select value={id || undefined} onValueChange={value => { setId(value); setName(value); }}>
          <SelectTrigger id="model-catalog"><SelectValue placeholder="请选择模型" /></SelectTrigger>
          <SelectContent>
            {id && !catalog.includes(id) && <SelectItem value={id}>{id}（手动配置）</SelectItem>}
            {catalog.map(value => <SelectItem key={value} value={value}>{value}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>}
      <div className="space-y-2"><Label htmlFor="model-id">模型 ID（支持手动填写）</Label>
        <Input id="model-id" value={id} onChange={e => setId(e.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="model-name">显示名称</Label>
        <Input id="model-name" value={name} onChange={e => setName(e.target.value)} placeholder={id} /></div>
      <div className="space-y-2"><Label htmlFor="model-description">描述</Label>
        <Input id="model-description" value={description} onChange={e => setDescription(e.target.value)} /></div>
      {kind === 'llm' && <div className="space-y-3">
        <p className="text-xs text-muted-foreground">模型容量（Token）：百炼官方 Qwen 3.7/3.8 商业型号自动识别；其他模型可按供应商规格填写。留空使用默认容量。</p>
        <div className="space-y-2"><Label htmlFor="model-context-window">上下文窗口</Label>
          <Input id="model-context-window" type="number" min={8192} step={1} value={contextWindow} onChange={e => setContextWindow(e.target.value)} placeholder="自动" /></div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2"><Label htmlFor="model-max-input">最大输入 Token</Label>
            <Input id="model-max-input" type="number" min={1024} step={1} value={maxInput} onChange={e => setMaxInput(e.target.value)} placeholder="自动" /></div>
          <div className="space-y-2"><Label htmlFor="model-max-output">最大输出 Token</Label>
            <Input id="model-max-output" type="number" min={256} step={1} value={maxOutput} onChange={e => setMaxOutput(e.target.value)} placeholder="自动" /></div>
        </div>
      </div>}
      {!model && catalog.length > 0 && <div className="flex gap-2 items-start">
        <Checkbox id="model-add-all" checked={addAll} onCheckedChange={checked => setAddAll(checked === true)} />
        <Label htmlFor="model-add-all" className="text-xs leading-relaxed">添加全部 {catalog.length} 个模型，均按当前模型类型配置（混合类型供应商请分别添加）</Label>
      </div>}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>取消</Button>
        <Button disabled={busy} onClick={confirm}>{model ? '确认修改' : '确认添加'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
