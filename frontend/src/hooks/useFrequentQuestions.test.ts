import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { apiRequest } from '../services/api';
import { useFrequentQuestions } from './useFrequentQuestions';
vi.mock('../services/api', () => ({apiRequest: vi.fn()}));
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });
const row = {id:'q',question:'销售额是多少？',count:3,last_asked_at:'2026-10-12T00:00:00Z'};

it('clears old scope immediately and ignores late responses after a resource switch', async () => {
  let resolveOld: (value: typeof row[]) => void;
  vi.mocked(apiRequest).mockImplementationOnce(() => new Promise(resolve => {resolveOld=resolve;}));
  vi.mocked(apiRequest).mockResolvedValueOnce([{...row,id:'new'}]);
  const {result,rerender} = renderHook(({kb}) => useFrequentQuestions(kb,[],true,3,false), {initialProps:{kb:['a']}});
  rerender({kb:['b']});
  expect(result.current).toEqual([]);
  await waitFor(() => expect(result.current[0]?.id).toBe('new'));
  await act(async () => {resolveOld([row]);});
  expect(result.current[0].id).toBe('new');
  expect(apiRequest).toHaveBeenLastCalledWith('/frequent-questions?kb_ids=b',expect.anything());
});

it('refreshes every five seconds, on answer completion and threshold changes; stops when disabled', async () => {
  vi.useFakeTimers(); vi.mocked(apiRequest).mockResolvedValue([row]);
  const {result,rerender,unmount} = renderHook(({enabled,loading,threshold}) => useFrequentQuestions([],[],enabled,threshold,loading),
    {initialProps:{enabled:true,loading:true,threshold:3}});
  await act(async () => {});
  expect(result.current).toEqual([row]);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(apiRequest).toHaveBeenCalledTimes(2);
  rerender({enabled:true,loading:false,threshold:3});
  await act(async () => {});
  expect(apiRequest).toHaveBeenCalledTimes(3);
  rerender({enabled:true,loading:false,threshold:4});
  await act(async () => {});
  expect(apiRequest).toHaveBeenCalledTimes(4);
  rerender({enabled:false,loading:false,threshold:4});
  expect(result.current).toEqual([]);
  await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
  expect(apiRequest).toHaveBeenCalledTimes(4);
  unmount();
});
