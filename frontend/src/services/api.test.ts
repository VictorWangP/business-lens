import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {apiRequest,setToken,getToken} from './api';
beforeEach(()=>{localStorage.clear();setToken('current-token');});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();localStorage.clear();});
it('reports HTTP status and revokes the current expired session',async()=>{
  const listener=vi.fn();window.addEventListener('auth:unauthorized',listener);
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:401,json:async()=>({detail:'登录已过期'})}));
  await expect(apiRequest('/auth/me')).rejects.toMatchObject({status:401,message:'登录已过期'});
  expect(getToken()).toBeNull();expect(listener).toHaveBeenCalledOnce();
  window.removeEventListener('auth:unauthorized',listener);
});
it('ignores a late authorization failure belonging to a previous login',async()=>{
  let finish:(value:unknown)=>void;
  vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=resolve;})));
  const listener=vi.fn();window.addEventListener('auth:unauthorized',listener);
  const request=apiRequest('/auth/me');const rejected=expect(request).rejects.toMatchObject({status:401});
  setToken('new-token');finish({ok:false,status:401,json:async()=>({detail:'旧账号凭据过期'})});
  await rejected;expect(getToken()).toBe('new-token');expect(listener).not.toHaveBeenCalled();
  window.removeEventListener('auth:unauthorized',listener);
});
