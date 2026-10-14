import React from 'react';
import {act,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {AuthProvider,useAuth} from './AuthContext';
import {apiRequest,setToken,getToken} from '../services/api';
vi.mock('../services/api',async importOriginal=>({...await importOriginal<typeof import('../services/api')>(),apiRequest:vi.fn()}));
const reviewer={id:'u',username:'核查员',role:'feedback_admin',created_at:'2026-10-13T00:00:00Z'};
function Monitor(){const {user,loading,login}=useAuth();return <><p>{loading ? '加载中' : `${user?.username || '未登录'}:${user?.role || ''}`}</p><button onClick={()=>login('new','test')}>切换账号</button></>;}
beforeEach(()=>{vi.resetAllMocks();localStorage.clear();setToken('original-token');});
afterEach(()=>localStorage.clear());
it('keeps the active account on a transient focus refresh failure',async()=>{
  vi.mocked(apiRequest).mockResolvedValueOnce(reviewer).mockRejectedValueOnce(new Error('暂时离线'));
  render(<AuthProvider><Monitor/></AuthProvider>);await screen.findByText('核查员:feedback_admin');
  await act(async()=>{window.dispatchEvent(new Event('focus'));});
  expect(screen.getByText('核查员:feedback_admin')).toBeInTheDocument();expect(getToken()).toBe('original-token');
});
it('removes feedback management access on a forbidden event',async()=>{
  vi.mocked(apiRequest).mockResolvedValue(reviewer);
  render(<AuthProvider><Monitor/></AuthProvider>);await screen.findByText('核查员:feedback_admin');
  act(()=>window.dispatchEvent(new Event('feedback:forbidden')));
  expect(screen.getByText('核查员:user')).toBeInTheDocument();expect(getToken()).toBe('original-token');
});
it('ignores an old identity response after login changed',async()=>{
  let finish:(value:unknown)=>void;
  vi.mocked(apiRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce({access_token:'new-token',user:{...reviewer,id:'new',username:'新用户',role:'user'}});
  render(<AuthProvider><Monitor/></AuthProvider>);
  await userEvent.setup().click(screen.getByRole('button',{name:'切换账号'}));
  await waitFor(()=>expect(getToken()).toBe('new-token'));
  await act(async()=>finish(reviewer));
  expect(screen.getByText('新用户:user')).toBeInTheDocument();
});
