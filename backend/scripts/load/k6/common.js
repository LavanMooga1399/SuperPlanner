// Shared helpers of the M8 load tests (M8-DESIGN 14.2). Auth: a session cookie from BASE_URL /auth/login, or an
// API token in TOKEN (Bearer). WORKSPACE (optional) = plant owner id for member accounts.
import http from 'k6/http';
import { check } from 'k6';

export const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';
export const API = `${BASE}/api/v1`;

export function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (__ENV.TOKEN) h.Authorization = `Bearer ${__ENV.TOKEN}`;
  if (__ENV.WORKSPACE) h['X-SP-Workspace'] = __ENV.WORKSPACE;
  return h;
}

export function login() {
  if (__ENV.TOKEN || !__ENV.EMAIL) return {};
  const r = http.post(`${API}/auth/login`, JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } });
  check(r, { 'login 200': (x) => x.status === 200 });
  return { csrf: r.json('csrf_token') };
}

export function get(path, tag) {
  const r = http.get(`${API}${path}`, { headers: headers(), tags: { name: tag || path } });
  check(r, { [`${tag || path} 200`]: (x) => x.status === 200 });
  return r;
}

export function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}
