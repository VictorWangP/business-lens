import type { DictationAdapter, SpeechSynthesisAdapter } from '@assistant-ui/react';
import { apiRequest, getToken } from '../services/api';

/** Bridge the existing audio services to assistant-ui, keeping device and request cleanup in one place. */
export function createAudioAdapters(onError: (message: string) => void, speechOptions: {voiceName?: string; speed?: number} = {}) {
  const active = new Set<() => void>();
  const report = (error: unknown) => onError(error instanceof Error ? error.message : '语音处理失败');
  const speech: SpeechSynthesisAdapter = {
    speak(text) {
      const listeners = new Set<() => void>();
      let utterance: SpeechSynthesisUtterance | undefined;
      let cancelled = false;
      const chunks = splitSpeechText(text);
      let chunkIndex = 0;
      const finish = (reason: 'finished' | 'cancelled' | 'error', error?: unknown) => {
        if (result.status.type === 'ended') return;
        result.status = {type:'ended', reason, error};
        active.delete(result.cancel);
        listeners.forEach(listener => listener());
        if (reason === 'error') report(error);
      };
      const speakNext = () => {
        if (cancelled) return;
        if (chunkIndex >= chunks.length) { finish('finished'); return; }
        utterance = new SpeechSynthesisUtterance(chunks[chunkIndex++]);
        utterance.lang = 'zh-CN';
        utterance.rate = Math.min(2, Math.max(0.5, speechOptions.speed ?? 1));
        const voices = typeof window.speechSynthesis?.getVoices === 'function' ? window.speechSynthesis.getVoices() : [];
        const requested = speechOptions.voiceName?.toLowerCase();
        const voice = (requested && voices.find(item => item.name.toLowerCase().includes(requested)))
          || voices.find(item => item.lang.toLowerCase().startsWith('zh'));
        if (voice) utterance.voice = voice;
        utterance.onend = speakNext;
        utterance.onerror = (event: any) => {
          if (!event || event.error === 'canceled' || event.error === 'interrupted' || cancelled) finish('cancelled');
          else finish('error', new Error('语音朗读失败，请重试。'));
        };
        window.speechSynthesis.speak(utterance);
      };
      const result: SpeechSynthesisAdapter.Utterance = {
        status:{type:'starting'},
        cancel() {
          if (result.status.type === 'ended') return;
          cancelled = true;
          finish('cancelled');
          window.speechSynthesis?.cancel?.();
        },
        subscribe(callback) {
          listeners.add(callback);
          if (result.status.type === 'ended') queueMicrotask(() => { if (listeners.has(callback)) callback(); });
          return () => { listeners.delete(callback); };
        },
      };
      active.add(result.cancel);
      try {
        if (!chunks.length) throw new Error('回答中没有可朗读的文字。');
        if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined' || !SpeechSynthesisUtterance) {
          const controller = new AbortController();
          result.cancel = () => {
            if (result.status.type === 'ended') return;
            cancelled = true;
            controller.abort();
            finish('cancelled');
          };
          result.status = {type:'running'};
          const token = getToken();
          void fetch(`/api/audio/synthesize?text=${encodeURIComponent(text)}`, {
            headers: token ? {Authorization: `Bearer ${token}`} : {},
            signal: controller.signal,
          }).then(async res => {
            if (!res.ok) throw new Error('语音服务不可用');
            const blob = await res.blob();
            if (cancelled) return;
            const url = URL.createObjectURL(blob);
            const player = new Audio(url);
            player.onended = () => {
              URL.revokeObjectURL(url);
              finish('finished');
            };
            player.onerror = () => {
              URL.revokeObjectURL(url);
              finish('error', new Error('语音播放失败'));
            };
            void player.play();
          }).catch(err => {
            if (!cancelled && err.name !== 'AbortError') finish('error', err);
          });
          return result;
        }
        result.status = {type:'running'};
        speakNext();
      } catch (error) { finish('error', error); }
      return result;
    },
  };
  const dictation: DictationAdapter = {
    disableInputDuringDictation:true,
    listen() {
      const starts = new Set<() => void>();
      const speeches = new Set<(result: DictationAdapter.Result) => void>();
      const ends = new Set<(result: DictationAdapter.Result) => void>();
      const controller = new AbortController();
      let stream: MediaStream | undefined;
      let recorder: MediaRecorder | undefined;
      let stopRequested = false;
      let resolveStopped: () => void;
      const stopped = new Promise<void>(resolve => { resolveStopped = resolve; });
      const release = () => stream?.getTracks().forEach(track => track.stop());
      const finish = (reason: 'stopped' | 'cancelled' | 'error') => {
        if (session.status.type === 'ended') return;
        session.status = {type:'ended',reason};
        release(); active.delete(session.cancel); resolveStopped();
        ends.forEach(callback => callback({transcript:''}));
      };
      const session: DictationAdapter.Session = {
        status:{type:'starting'},
        async stop() {
          stopRequested = true;
          if (recorder?.state === 'recording') recorder.stop();
          return stopped;
        },
        cancel() {
          controller.abort();
          if (recorder?.state === 'recording') recorder.stop();
          finish('cancelled');
        },
        onSpeechStart(callback) { starts.add(callback); return () => { starts.delete(callback); }; },
        onSpeech(callback) { speeches.add(callback); return () => { speeches.delete(callback); }; },
        onSpeechEnd(callback) { ends.add(callback); return () => { ends.delete(callback); }; },
      };
      active.add(session.cancel);
      // listen must return synchronously; permission and transcription stay inside this cancellable session.
      void (async () => {
        try {
          if (!window.isSecureContext) throw new Error('麦克风访问需要安全连接，请使用 HTTPS 或 localhost 打开页面。');
          if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
            throw new Error('当前浏览器不支持录音，请使用最新版 Chrome、Edge 或 Safari。');
          }
          stream = await navigator.mediaDevices.getUserMedia({audio:true});
          if (controller.signal.aborted || stopRequested) { release(); finish(controller.signal.aborted ? 'cancelled' : 'stopped'); return; }
          recorder = new MediaRecorder(stream);
          const chunks: BlobPart[] = [];
          recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
          recorder.onstop = async () => {
            release();
            if (controller.signal.aborted) return;
            try {
              const mime = recorder.mimeType || 'audio/webm';
              const form = new FormData();
              form.append('file', new Blob(chunks, {type:mime}), mime.includes('mp4') ? 'recording.mp4' : 'recording.webm');
              const result = await apiRequest<{text:string}>('/audio/transcribe', {method:'POST',body:form,signal:controller.signal});
              if (controller.signal.aborted) return;
              if (result.text) speeches.forEach(callback => callback({transcript:result.text,isFinal:true}));
              finish('stopped');
            } catch (error) { if (!controller.signal.aborted) { finish('error'); report(microphoneErrorMessage(error)); } }
          };
          recorder.onerror = () => { controller.abort(); finish('error'); report(new Error('录音过程中麦克风不可用，请检查设备连接和系统输入设置后重试。')); };
          recorder.start(); session.status = {type:'running'}; starts.forEach(callback => callback());
        } catch (error) { if (!controller.signal.aborted) { finish('error'); report(microphoneErrorMessage(error)); } }
      })();
      return session;
    },
  };
  return {speech, dictation, dispose() { [...active].forEach(cancel => cancel()); }};
}

function microphoneErrorMessage(error: unknown): Error {
  const name = error instanceof Error ? error.name : '';
  const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || message.includes('device not found')) {
    return new Error('未检测到麦克风。请连接麦克风，并在系统声音设置中确认有可用的输入设备。');
  }
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return new Error('麦克风权限未开启。请允许浏览器访问麦克风，并检查系统的麦克风隐私权限。');
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return new Error('麦克风当前无法使用。请关闭占用麦克风的其他应用，或检查系统输入设备后重试。');
  }
  if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
    return new Error('当前麦克风不满足录音要求。请在系统设置中切换可用的输入设备后重试。');
  }
  return error instanceof Error ? error : new Error('无法启动录音，请检查麦克风权限和设备状态后重试。');
}

function splitSpeechText(source: string): string[] {
  const text = source
    .replace(/```[\s\S]*?```/g, '代码内容已省略。')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!?\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, '$1')
    .replace(/\|/g, '，')
    .replace(/\[(\d+)\]/g, '，引用$1，')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{2,}/g, '。')
    .trim();
  if (!text) return [];
  const sentences = text.split(/(?<=[。！？!?；;\n])/).map(part => part.trim()).filter(Boolean);
  const chunks: string[] = [];
  let current = '';
  for (const sentence of sentences) {
    if (sentence.length > 240) {
      if (current) chunks.push(current);
      current = '';
      for (let index = 0; index < sentence.length; index += 240) chunks.push(sentence.slice(index, index + 240));
    } else if (current.length + sentence.length > 240) {
      chunks.push(current);
      current = sentence;
    } else current += sentence;
  }
  if (current) chunks.push(current);
  return chunks;
}
