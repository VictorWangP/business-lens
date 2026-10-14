import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { createAudioAdapters } from './audio-adapters';
import { apiRequest } from '../services/api';
vi.mock('../services/api', () => ({apiRequest:vi.fn(), getToken:() => 'token'}));
class Recorder {
  state = 'inactive'; mimeType = 'audio/webm';
  ondataavailable: (event:any) => void; onstop: () => void; onerror: () => void;
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; this.ondataavailable?.({data:new Blob(['audio'])}); this.onstop?.(); }
}
let adapters: ReturnType<typeof createAudioAdapters>;
let stopTrack: ReturnType<typeof vi.fn>;
let onError: ReturnType<typeof vi.fn>;
beforeEach(() => {
  stopTrack=vi.fn(); onError=vi.fn(); adapters=createAudioAdapters(onError);
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockResolvedValue({getTracks:() => [{stop:stopTrack}]})}});
  vi.stubGlobal('MediaRecorder',Recorder);
  vi.stubGlobal('isSecureContext',true);
  vi.mocked(apiRequest).mockReset();
});
afterEach(() => { adapters.dispose(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('assistant-ui audio service adapters', () => {
  it('rejects microphone access outside a secure browser context', () => {
    vi.stubGlobal('isSecureContext',false);
    const session=adapters.dictation.listen();
    expect(session.status).toEqual({type:'ended',reason:'error'});
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('安全连接'));
  });
  it('transcribes the recording and releases the microphone before completing the session', async () => {
    vi.mocked(apiRequest).mockResolvedValue({text:'销售收入'});
    const session=adapters.dictation.listen(); const transcript=vi.fn(); session.onSpeech(transcript);
    await waitFor(() => expect(session.status.type).toBe('running'));
    await session.stop();
    expect(transcript).toHaveBeenCalledWith({transcript:'销售收入',isFinal:true});
    expect(stopTrack).toHaveBeenCalled();
    expect(apiRequest).toHaveBeenCalledWith('/audio/transcribe',expect.objectContaining({method:'POST',body:expect.any(FormData)}));
    expect(session.status).toEqual({type:'ended',reason:'stopped'});
  });
  it('releases late microphone permission without uploading when navigation cancels a session', async () => {
    let grant: (stream:any) => void;
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(new Promise(resolve => {grant=resolve;}));
    const session=adapters.dictation.listen(); adapters.dispose();
    grant({getTracks:() => [{stop:stopTrack}]});
    await waitFor(() => expect(stopTrack).toHaveBeenCalled());
    expect(session.status).toEqual({type:'ended',reason:'cancelled'});
    expect(apiRequest).not.toHaveBeenCalled();
  });
  it('ignores a late transcript after switching conversations', async () => {
    let finish: (value:any) => void;
    vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => {finish=resolve;}));
    const session=adapters.dictation.listen(); const transcript=vi.fn(); session.onSpeech(transcript);
    await waitFor(() => expect(session.status.type).toBe('running'));
    const stopped=session.stop();
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    adapters.dispose(); finish({text:'旧会话录音'}); await stopped;
    expect(transcript).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
  it('reports transcription errors and permits the native composer to leave dictation mode', async () => {
    vi.mocked(apiRequest).mockRejectedValue(new Error('语音服务不可用'));
    const session=adapters.dictation.listen(); const ended=vi.fn(); session.onSpeechEnd(ended);
    await waitFor(() => expect(session.status.type).toBe('running'));
    await session.stop();
    expect(session.status).toEqual({type:'ended',reason:'error'});
    expect(ended).toHaveBeenCalled(); expect(onError).toHaveBeenCalledWith('语音服务不可用');
  });
  it('supports native speech stop without displaying cancellation as an error', () => {
    let current: any;
    vi.stubGlobal('SpeechSynthesisUtterance',class {lang=''; onend:()=>void; onerror:()=>void; constructor(public text:string){current=this;}});
    Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{speak:vi.fn(),cancel:vi.fn(() => current.onerror?.())}});
    const utterance=adapters.speech.speak('销售回答'); const listener=vi.fn(); utterance.subscribe(listener);
    expect(current.lang).toBe('zh-CN');
    adapters.dispose();
    expect(utterance.status).toEqual({type:'ended',reason:'cancelled',error:undefined});
    expect(window.speechSynthesis.cancel).toHaveBeenCalled(); expect(listener).toHaveBeenCalled(); expect(onError).not.toHaveBeenCalled();
  });
  it('authenticates backend speech synthesis and releases the audio URL on completion', async () => {
    vi.stubGlobal('SpeechSynthesisUtterance', undefined);
    const fetchAudio=vi.fn().mockResolvedValue({ok:true,blob:async () => new Blob(['audio'])});
    vi.stubGlobal('fetch',fetchAudio);
    const createUrl=vi.fn().mockReturnValue('blob:answer');
    const revokeUrl=vi.fn();
    vi.stubGlobal('URL',Object.assign(class extends URL {},{createObjectURL:createUrl,revokeObjectURL:revokeUrl}));
    let player: any;
    vi.stubGlobal('Audio',class {onended:()=>void; onerror:()=>void; play=vi.fn().mockResolvedValue(undefined); pause=vi.fn(); constructor(public src:string){player=this;}});
    const utterance=adapters.speech.speak('销售收入');
    await waitFor(() => expect(utterance.status.type).toBe('running'));
    expect(fetchAudio).toHaveBeenCalledWith(expect.stringContaining('/api/audio/synthesize?text='),expect.objectContaining({headers:{Authorization:'Bearer token'},signal:expect.any(AbortSignal)}));
    expect(player.src).toBe('blob:answer');
    player.onended();
    expect(utterance.status).toEqual({type:'ended',reason:'finished',error:undefined});
    expect(revokeUrl).toHaveBeenCalledWith('blob:answer'); expect(onError).not.toHaveBeenCalled();
  });
});
