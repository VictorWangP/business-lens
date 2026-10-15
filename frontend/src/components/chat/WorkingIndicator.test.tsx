import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkingIndicator } from './WorkingIndicator';
import { RunTimingContext } from './RunTimingContext';
import type { Message } from '../../types/chat';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('WorkingIndicator timing', () => {
  it('keeps the persisted start time when a resumed message is recreated', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-14T00:01:00Z'));
    const message: Message = { id: 'a', conversation_id: 't', role: 'assistant',
      content: '', created_at: '2026-10-14T00:01:00Z' };
    const view = () => render(<RunTimingContext.Provider value="2026-10-14T00:00:00">
      <WorkingIndicator message={message} />
    </RunTimingContext.Provider>);
    const first = view();
    expect(screen.getByText('60 秒')).toBeTruthy();
    first.unmount();
    act(() => { vi.advanceTimersByTime(10000); });
    message.created_at = new Date().toISOString();
    view();
    expect(screen.getByText('70 秒')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByText('71 秒')).toBeTruthy();
  });

  it('uses the new message start time for a fresh run', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-14T00:01:00Z'));
    render(<WorkingIndicator message={{ id: 'b', conversation_id: 't', role: 'assistant',
      content: '', created_at: '2026-10-14T00:00:58Z' }} />);
    expect(screen.getByText('2 秒')).toBeTruthy();
  });
});
