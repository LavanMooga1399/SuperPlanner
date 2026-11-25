// L1: 300 virtual users, read-heavy mix for 30 minutes (p95 < 800 ms, errors < 0.1 %).
import { sleep } from 'k6';
import { get, login, pick } from './common.js';

export const options = {
  scenarios: { read: { executor: 'constant-vus', vus: Number(__ENV.VUS || 300), duration: __ENV.DURATION || '30m' } },
  thresholds: { http_req_duration: ['p(95)<800'], http_req_failed: ['rate<0.001'] },
};

export function setup() {
  login();
  const items = get('/mfg/items?limit=200', 'items').json('items').map((x) => x.id);
  const runs = get('/mfg/rate/runs?limit=5', 'rate runs').json('items').map((x) => x.id);
  const mrp = get('/mfg/mrp/runs/latest', 'mrp latest').json('id');
  return { items, runs, mrp };
}

export default function (d) {
  const r = Math.random();
  if (r < 0.2) get('/mfg/dashboard', 'dashboard');
  else if (r < 0.4 && d.mrp) get(`/mfg/mrp/runs/${d.mrp}/items/${pick(d.items)}`, 'mrp item');
  else if (r < 0.55 && d.runs.length) get(`/mfg/rate/runs/${d.runs[0]}/grid?bucket=day`, 'rate grid');
  else if (r < 0.75) get(`/mfg/forecast/items/${pick(d.items)}`, 'forecast item');
  else if (r < 0.85) get('/mfg/work-orders?limit=50', 'work orders');
  else if (r < 0.95) get('/mfg/ster/loads?limit=50', 'ster loads');
  else get('/mfg/demand-orders?limit=50', 'demand orders');
  sleep(Math.random() * 2 + 0.5);
}
