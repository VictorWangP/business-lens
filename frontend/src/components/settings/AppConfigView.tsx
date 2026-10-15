import React, { useEffect, useState } from 'react';
import {
  MessageSquare,
  ListOrdered,
  Volume2,
  Mic,
  Box,
  Flame,
  Settings as GearIcon
} from 'lucide-react';
import { useConfig } from '../../context/ConfigContext';
import { ConfigModals } from './ConfigModals';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Skeleton } from '../ui/skeleton';
import { Switch } from '../ui/switch';
import { Button } from '../ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { toast } from 'sonner';

// 各配置卡片的图标背景色 — 保留差异化色彩但简化写法
const iconClass = {
  blue: 'bg-primary/10 text-primary',
  amber: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  emerald: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  purple: 'bg-purple-500/10 text-purple-600 dark:text-purple-400',
};

export const AppConfigView: React.FC = () => {
  const { configs, toggleConfig, updateConfig, refreshConfigs } = useConfig();
  const [modalType, setModalType] = useState<string | null>(null);
  const [chineseVoices, setChineseVoices] = useState<SpeechSynthesisVoice[]>([]);

  useEffect(() => {
    if (!('speechSynthesis' in window)) return;
    const loadVoices = () => setChineseVoices(window.speechSynthesis.getVoices().filter(voice => voice.lang.toLowerCase().startsWith('zh')));
    loadVoices();
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', loadVoices);
  }, []);

  const saveVoicePreference = async (changes: {voice_name?: string; speed?: number}) => {
    if (!configs) return;
    try { await updateConfig('voice_tts', {...configs.voice_tts, ...changes}); }
    catch { toast.error('语音偏好保存失败，请重试。'); }
  };

  if (!configs) {
    return (
      <div className="p-8 text-muted-foreground">
        <p role="status" className="mb-4">正在加载应用配置…</p>
        <div className="grid md:grid-cols-3 gap-6">
          {[0, 1, 2].map(key => <Skeleton key={key} className="h-36 rounded-xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-background text-foreground p-8 max-w-7xl mx-auto space-y-6">
      {/* 顶部标题栏 */}
      <div>
        <div className="text-xs font-semibold text-muted-foreground tracking-wider">
          系统管理 / 应用配置
        </div>
      </div>

      {/* 应用行为与模型配置 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* 卡片 1: 对话开场白 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.blue}`}>
                <MessageSquare className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">对话开场白</CardTitle>
            </div>
            <div className="flex items-center space-x-1">
              <Button variant="ghost" size="icon"
                onClick={() => setModalType('welcome')}
                title="设置开场白内容"
              >
                <GearIcon className="w-4 h-4" />
              </Button>
              <Switch aria-label="启用welcome_setting" checked={configs.welcome_setting.is_enabled} onCheckedChange={() => toggleConfig('welcome_setting')} />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              开启后，新对话将自动显示开场白引导语（如"{configs.welcome_setting.description?.slice(0, 15) || '欢迎使用智能AI问数'}..."）
            </p>
          </CardContent>
        </Card>

        {/* 卡片 2: 下一步问题建议 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.amber}`}>
                <ListOrdered className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">下一步问题建议</CardTitle>
            </div>
            <Switch aria-label="启用next_questions" checked={configs.next_questions.is_enabled} onCheckedChange={() => toggleConfig('next_questions')} />
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              开启后，AI回复下方自动生成3条相关延伸问题提示条
            </p>
          </CardContent>
        </Card>

        {/* 卡片 3: 文字转语音 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.emerald}`}>
                <Volume2 className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">文字转语音</CardTitle>
            </div>
            <Switch aria-label="启用文字转语音" checked={configs.voice_tts.is_enabled} onCheckedChange={() => toggleConfig('voice_tts')} />
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              使用当前设备的浏览器语音朗读 AI 回答；音色取决于设备提供的中文语音。
            </p>
            <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3">
              <Select value={chineseVoices.some(voice => voice.name === configs.voice_tts.voice_name) ? configs.voice_tts.voice_name : (chineseVoices[0]?.name || '')}
                onValueChange={voice_name => void saveVoicePreference({voice_name})} disabled={!chineseVoices.length}>
                <SelectTrigger aria-label="选择朗读音色" className="h-9"><SelectValue placeholder="使用设备默认中文音色" /></SelectTrigger>
                <SelectContent>{chineseVoices.map(voice => <SelectItem key={`${voice.name}-${voice.lang}`} value={voice.name}>{voice.name}（{voice.lang}）{voice.localService ? '' : ' · 在线'}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={String(configs.voice_tts.speed)} onValueChange={value => void saveVoicePreference({speed: Number(value)})}>
                <SelectTrigger aria-label="选择朗读语速" className="h-9 w-28"><SelectValue /></SelectTrigger>
                <SelectContent>{[['0.8','较慢'],['1','正常'],['1.2','稍快'],['1.5','快速']].map(([value,label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {!chineseVoices.length && <p className="mt-2 text-xs text-muted-foreground">暂未检测到中文音色，将使用浏览器默认音色。</p>}
          </CardContent>
        </Card>

        {/* 卡片 4: 语音转文字 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.purple}`}>
                <Mic className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">语音转文字</CardTitle>
            </div>
            <Switch aria-label="启用语音转文字" checked={configs.voice_stt.is_enabled} onCheckedChange={() => toggleConfig('voice_stt')} />
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              录音需要浏览器麦克风权限，并发送到百炼 qwen3-asr-flash 识别；请在模型配置中将默认对话模型设为百炼。非本地访问请使用 HTTPS。
            </p>
          </CardContent>
        </Card>

        {/* 卡片 5: 模型配置 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.blue}`}>
                <Box className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">模型配置</CardTitle>
            </div>
            <div className="flex items-center space-x-1">
              <Button variant="ghost" size="icon"
                onClick={() => setModalType('model')}
                title="配置模型参数"
              >
                <GearIcon className="w-4 h-4" />
              </Button>
              <Switch aria-label="启用model_setting" checked={configs.model_setting.is_enabled} onCheckedChange={() => toggleConfig('model_setting')} />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              配置各业务场景使用的AI模型（主力对话：{configs.model_setting.default_model}，常问分组嵌入：{configs.model_setting.default_embedding_model || '未配置'}）
            </p>
          </CardContent>
        </Card>

        {/* 卡片 6: 常问设置 */}
        <Card className="shadow-sm hover:shadow-md transition">
          <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${iconClass.amber}`}>
                <Flame className="w-5 h-5" />
              </div>
              <CardTitle className="text-base font-semibold">常问设置</CardTitle>
            </div>
            <div className="flex items-center space-x-1">
              <Button variant="ghost" size="icon"
                onClick={() => setModalType('frequent')}
                title="设置常问快捷问题"
              >
                <GearIcon className="w-4 h-4" />
              </Button>
              <Switch aria-label="启用frequent_questions" checked={configs.frequent_questions.is_enabled} onCheckedChange={() => toggleConfig('frequent_questions')} />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground leading-relaxed">
              根据相似提问频次（阈值：{configs.frequent_questions.threshold || 3} 次），在快捷提问中展示常问问题，按当前资源范围统计，最多展示 10 条
            </p>
            {configs.frequent_questions.reset_required && <p className="mt-2 text-xs text-destructive">嵌入模型已变化，常问统计暂停。请进入常问设置重置统计。</p>}
          </CardContent>
        </Card>
      </div>

      {/* 弹窗组件 */}
      {modalType && <ConfigModals
        type={modalType}
        configs={configs}
        onReset={refreshConfigs}
        onClose={() => setModalType(null)}
        onSave={async (key, val) => {
          await updateConfig(key, val);
          setModalType(null);
        }}
      />}
    </div>
  );
};
