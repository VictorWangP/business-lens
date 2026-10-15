const API_BASE = '/api';

export function getToken(): string | null {
  return localStorage.getItem('rag_token');
}

export function setToken(token: string) {
  localStorage.setItem('rag_token', token);
}

export function removeToken() {
  localStorage.removeItem('rag_token');
}

export async function apiRequest<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && token === getToken()) {
    removeToken();
    window.dispatchEvent(new Event('auth:unauthorized'));
  }

  if (!response.ok) {
    let errorDetail = '请求失败';
    try {
      const errJson = await response.json();
      const detail = errJson.detail;
      errorDetail = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg || '输入有误').join('；') : errorDetail;
    } catch {}
    const error = Object.assign(new Error(errorDetail), {status:response.status});
    if (response.status === 403 && token === getToken() && path.startsWith('/feedback')) window.dispatchEvent(new Event('feedback:forbidden'));
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}
