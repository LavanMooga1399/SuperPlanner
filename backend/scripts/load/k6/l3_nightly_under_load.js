// L3: the nightly chain started while 50 users read (P6 < 20 min; API p95 < 1.5 s).
import http from 'k6/http';
import { sleep } from 'k6';
import { API, get, headers, login } from './common.js';

export const options = {
  scenarios: {
    readers: { executor: 'constant-vus', vus: 50, duration: __ENV.DURATION || '25m', exec: 'read' },
    chain: { executor: 'shared-iterations', vus: 1, iterations: 1, exec: 'chain' },
  },
  thresholds: { 'http_req_duration{scenario:readers}': ['p(95)<1500'] },
};

export function setup() { login(); }

export function read() {
  get('/mfg/dashboard', 'dashboard');
  get('/mfg/rate/runs?limit=5', 'rate runs');
  sleep(1);
}

export function chain() {
  http.post(`${API}/mfg/planning/nightly/run-now`, '{}', { headers: headers() });
}
