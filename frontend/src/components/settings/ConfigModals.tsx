import React, { useState } from 'react';
import { Plus, Pencil, Trash2, Loader2, Star } from 'lucide-react';
import { AppConfigs, ModelItem } from '../../types/config';
import { apiRequest } from '../../services/api';
import { ModelEditor } from './ModelEditor';
import { Alert, AlertDescription } from '../ui/alert';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Label } from '../ui/label';
import { Slider } from '../ui/slider';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '../ui/alert-dialog';

interface ConfigModalsProps {
  type: string | null; configs: AppConfigs; onClose: () => void;
  onReset?: () => Promise<void>;
  onSave: (key: string, value: any) => Promise<void>;
}

export const ConfigModals: React.FC<ConfigModalsProps> = ({ type, configs, onClose, onSave, onReset }) => {
  // 1. 开场白设置状态
  const [welcomeGreeting, setWelcomeGreeting] = useState(
    configs.welcome_setting.greeting || '你好'
  );
  const [welcomeAssistantName, setWelcomeAssistantName] = useState(
    configs.welcome_setting.assistant_name || '我是经管之星·AI问数助手'
  );
  const [welcomeDesc, setWelcomeDesc] = useState(
    configs.welcome_setting.description ||
      '欢迎使用智能AI问数，您可以向我咨询经营数据、报表分析相关问题。'
  );
  const [welcomeQuestions, setWelcomeQuestions] = useState<string[]>(
    Array.isArray(configs.welcome_setting?.questions)
      ? [...configs.welcome_setting.questions]
      : []
  );

  // 2. 模型配置状态
  const [defaultModel, setDefaultModel] = useState(configs.model_setting.default_model);
  const [defaultEmbeddingModel, setDefaultEmbeddingModel] = useState(
    configs.model_setting.default_embedding_model || ''
  );
  const [temperature, setTemperature] = useState(configs.model_setting.temperature);
  const [modelsList, setModelsList] = useState<ModelItem[]>([
    ...configs.model_setting.available_models,
  ]);

  const [showAddModelModal, setShowAddModelModal] = useState(false);
  const [editingModel, setEditingModel] = useState<ModelItem | undefined>();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [pendingRemove, setPendingRemove] = useState<ModelItem | null>(null);

  // 3. 常问问题状态
  const [frequentThreshold, setFrequentThreshold] = useState<number>(
    configs.frequent_questions.threshold || 3
  );
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetDone, setResetDone] = useState(false);

  // 处理添加开场问题（最多 10 条）
  const handleAddWelcomeQuestion = () => {
    if (welcomeQuestions.length >= 10) return;
    setWelcomeQuestions([...welcomeQuestions, '']);
  };

  const handleUpdateWelcomeQuestion = (index: number, val: string) => {
    const updated = [...welcomeQuestions];
    updated[index] = val;
    setWelcomeQuestions(updated);
  };

  const handleRemoveWelcomeQuestion = (index: number) => {
    setWelcomeQuestions(welcomeQuestions.filter((_, i) => i !== index));
  };

  const handleConfirmModels = (items: ModelItem[], previousId?: string) => {
    const ids = new Set(items.map(item => item.id));
    const updated = [...modelsList.filter(item => item.id !== previousId && !ids.has(item.id)), ...items];
    setModelsList(updated);
    const first = items[0];
    setDefaultModel(first.type !== 'embedding' && (!previousId || previousId === defaultModel) ? first.id
      : updated.some(item => item.id === defaultModel && item.type !== 'embedding') ? defaultModel
      : updated.find(item => item.type !== 'embedding')?.id || '');
    setDefaultEmbeddingModel(first.type === 'embedding' && (!previousId || previousId === defaultEmbeddingModel) ? first.id
      : updated.some(item => item.id === defaultEmbeddingModel && item.type === 'embedding') ? defaultEmbeddingModel
      : updated.find(item => item.type === 'embedding')?.id || '');
    setShowAddModelModal(false);
  };

  const handleRemoveModel = (id: string) => {
    const updated = modelsList.filter((m) => m.id !== id);
    setModelsList(updated);
    if (defaultModel === id) {
      const remainingLlm = updated.filter((m) => m.type !== 'embedding');
      setDefaultModel(remainingLlm[0]?.id || '');
    }
    if (defaultEmbeddingModel === id) {
      const remainingEmb = updated.filter((m) => m.type === 'embedding');
      setDefaultEmbeddingModel(remainingEmb[0]?.id || '');
    }
  };

  async function save() {
    setSaving(true); setSaveError('');
    try {
      if (type === 'welcome') await onSave('welcome_setting', {
        greeting: welcomeGreeting, assistant_name: welcomeAssistantName, description: welcomeDesc,
        questions: welcomeQuestions.filter(q => q.trim()).slice(0, 10),
      });
      if (type === 'model') await onSave('model_setting', {
        default_model: defaultModel, default_embedding_model: defaultEmbeddingModel,
        temperature, available_models: modelsList,
      });
      if (type === 'frequent') {
        if (!Number.isSafeInteger(frequentThreshold) || frequentThreshold < 1) throw new Error('阈值必须为正整数');
        await onSave('frequent_questions', { threshold: frequentThreshold });
      }
    } catch (err) { setSaveError(err instanceof Error ? err.message : '保存失败'); }
    finally { setSaving(false); }
  }

  const titles: Record<string, string> = {welcome: '对话开场白', model: '模型配置与推理参数', frequent: '常问设置'};
  return <Dialog open={!!type} onOpenChange={open => { if (!open && !saving) onClose(); }}>
    <DialogContent className="max-w-xl max-h-[90dvh] overflow-y-auto" onEscapeKeyDown={e => { if (saving) e.preventDefault(); }}>
      <DialogHeader><DialogTitle>{titles[type || '']}</DialogTitle>
        <DialogDescription>调整应用配置，点击保存后生效。</DialogDescription></DialogHeader>
      {type === 'welcome' && <div className="space-y-4">
        <div className="space-y-2"><Label htmlFor="welcome-greeting">问候语</Label><Input id="welcome-greeting" value={welcomeGreeting} onChange={e => setWelcomeGreeting(e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="welcome-name">助手名称</Label><Input id="welcome-name" value={welcomeAssistantName} onChange={e => setWelcomeAssistantName(e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="welcome-description">开场白文案</Label><Textarea id="welcome-description" rows={4} value={welcomeDesc} onChange={e => setWelcomeDesc(e.target.value)} /></div>
        <div className="space-y-2.5 pt-2 border-t border-border">
          <div className="flex items-center justify-between">
            <Label className="text-xs font-semibold text-foreground">开场问题 · {welcomeQuestions.length}/10</Label>
            <Button variant="outline" size="sm" className="h-8 gap-1.5" disabled={welcomeQuestions.length >= 10} onClick={handleAddWelcomeQuestion}>
              <Plus className="w-3.5 h-3.5" />
              <span>添加开场问题</span>
            </Button>
          </div>
          <div className="space-y-2">
            {welcomeQuestions.map((q, index) => <div key={index} className="flex items-center gap-2">
              <Input aria-label={`开场问题 ${index + 1}`} value={q} onChange={e => handleUpdateWelcomeQuestion(index, e.target.value)} placeholder={`推荐问题 ${index + 1}...`} />
              <Button variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-destructive" aria-label={`删除开场问题 ${index + 1}`} onClick={() => handleRemoveWelcomeQuestion(index)}>
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>)}
          </div>
        </div>
      </div>}
      {type === 'model' && <div className="space-y-5">
        <div className="space-y-2"><Label htmlFor="default-llm">默认对话模型</Label>
          <Select value={defaultModel || undefined} onValueChange={setDefaultModel}>
            <SelectTrigger id="default-llm"><SelectValue placeholder="请选择对话模型" /></SelectTrigger>
            <SelectContent>{modelsList.filter(m => m.type !== 'embedding').map(m => <SelectItem key={m.id} value={m.id}>[{m.provider || '通用'}] {m.name} ({m.id})</SelectItem>)}</SelectContent>
          </Select></div>
        <div className="space-y-2"><Label htmlFor="default-embedding">常问分组嵌入模型</Label>
          <Select value={defaultEmbeddingModel || '__none__'} onValueChange={value => setDefaultEmbeddingModel(value === '__none__' ? '' : value)}>
            <SelectTrigger id="default-embedding"><SelectValue placeholder="请选择嵌入模型" /></SelectTrigger>
            <SelectContent><SelectItem value="__none__">暂不配置嵌入模型</SelectItem>
              {modelsList.filter(m => m.type === 'embedding').map(m => <SelectItem key={m.id} value={m.id}>[{m.provider || '通用'}] {m.name} ({m.id})</SelectItem>)}
            </SelectContent>
          </Select><p className="text-xs text-muted-foreground">用于常问问题的语义归组，不出现在对话模型列表中。</p></div>
        <div className="space-y-3"><div className="flex justify-between"><Label htmlFor="model-temperature">采样温度 (Temperature)</Label><span className="text-sm tabular-nums text-primary">{temperature}</span></div>
          <Slider id="model-temperature" aria-label="采样温度" min={0} max={1.5} step={0.1} value={[temperature]} onValueChange={values => setTemperature(values[0])} />
          <p className="text-xs text-muted-foreground">较低数值输出更精确，较高数值输出更多样。</p></div>
        <div className="space-y-3 pt-2 border-t border-border">
          <div className="flex items-center justify-between">
            <Label className="text-xs font-semibold text-foreground">可用模型列表 ({modelsList.length})</Label>
            <Button size="sm" className="h-8 gap-1.5" onClick={() => { setEditingModel(undefined); setShowAddModelModal(true); }}>
              <Plus className="w-3.5 h-3.5" />
              <span>新增模型</span>
            </Button>
          </div>
          <div className="space-y-2">{modelsList.map(m => {
            const isEmbedding = m.type === 'embedding';
            const isDefault = m.id === (isEmbedding ? defaultEmbeddingModel : defaultModel);
            return <div key={m.id} className="rounded-xl border border-border bg-muted/20 p-3.5 space-y-2 hover:border-primary/50 transition">
              <div className="flex flex-wrap gap-2 items-center"><span className="font-medium text-sm text-foreground">{m.name}</span>
                <Badge variant="secondary">{m.provider || '通用'}</Badge><Badge variant="outline">{isEmbedding ? 'Embedding' : 'LLM'}</Badge>{isDefault && <Badge>默认</Badge>}</div>
              <p className="text-xs text-muted-foreground break-all">{m.base_url} · {m.id}</p>
              <div className="flex flex-wrap justify-end gap-1">
                {!isDefault && <Button variant="ghost" size="sm" onClick={() => isEmbedding ? setDefaultEmbeddingModel(m.id) : setDefaultModel(m.id)}><Star className="w-3.5 h-3.5 mr-1 text-primary" />设为默认</Button>}
                <Button variant="outline" size="sm" aria-label={`编辑模型 ${m.name}`} onClick={() => { setEditingModel(m); setShowAddModelModal(true); }}><Pencil className="w-3.5 h-3.5 mr-1" />编辑</Button>
                <Button variant="ghost" size="icon" aria-label={`删除模型 ${m.name}`} disabled={modelsList.length <= 1} onClick={() => setPendingRemove(m)}><Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" /></Button>
              </div>
            </div>;
          })}</div>
        </div>
      </div>}
      {type === 'frequent' && <div className="space-y-4">
        <div className="space-y-2"><Label htmlFor="frequent-threshold">常问问题展示次数阈值</Label><Input id="frequent-threshold" type="number" min={1} step={1} value={Number.isNaN(frequentThreshold) ? '' : frequentThreshold} onChange={e => setFrequentThreshold(e.target.valueAsNumber)} /></div>
        <p className="text-sm text-muted-foreground">根据独立完整问题的提问次数自动生成，按当前业务数据源范围分别统计，最多展示 10 条。手工推荐请在开场白中配置。</p>
        {configs.frequent_questions.reset_required && !resetDone && <Alert variant="destructive"><AlertDescription>嵌入模型已变化，统计暂停。重置后从新提问开始累计。</AlertDescription></Alert>}
        <Button variant="outline" disabled={saving} onClick={() => setConfirmReset(true)}>重置常问统计</Button>
        {resetDone && <p role="status" className="text-sm">已重置，从新提问开始累计。</p>}
      </div>}
      {saveError && <Alert variant="destructive"><AlertDescription>{saveError}</AlertDescription></Alert>}
      <DialogFooter><Button variant="outline" disabled={saving} onClick={onClose}>取消</Button><Button disabled={saving} onClick={save}>{saving && <Loader2 className="animate-spin" />}{saving ? '正在保存…' : '保存'}</Button></DialogFooter>
    </DialogContent>
    {showAddModelModal && <ModelEditor model={editingModel} models={modelsList} onClose={() => setShowAddModelModal(false)} onConfirm={handleConfirmModels} />}
    <AlertDialog open={confirmReset} onOpenChange={setConfirmReset}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>重置常问统计？</AlertDialogTitle><AlertDialogDescription>清除当前用户的常问分组与统计记录，从新提问开始累计。聊天消息及业务数据保留。</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={async () => {
          setSaving(true); setSaveError('');
          try { await apiRequest('/frequent-questions', {method: 'DELETE'}); setResetDone(true); await onReset?.(); }
          catch (err) { setSaveError(err instanceof Error ? err.message : '重置失败'); }
          finally { setSaving(false); }
        }}>确认重置</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <AlertDialog open={!!pendingRemove} onOpenChange={open => { if (!open) setPendingRemove(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>删除模型？</AlertDialogTitle><AlertDialogDescription>将从配置中移除 {pendingRemove?.name}，主弹窗保存后生效。</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => { if (pendingRemove) handleRemoveModel(pendingRemove.id); setPendingRemove(null); }}>确认删除</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </Dialog>;
};
