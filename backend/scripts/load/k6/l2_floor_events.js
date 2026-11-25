// L2: 2,000 floor events per hour (start / report / complete / scan) concurrent with L1 (p95 < 300 ms).
import http from 'k6/http';
import { check } from 'k6';
import { API, get, headers, login, pick } from './common.js';

export const options = {
  scenarios: { floor: { executor: 'constant-arrival-rate', rate: Number(__ENV.EVENTS_PER_HOUR || 2000),
    timeUnit: '1h', duration: __ENV.DURATION || '30m', preAllocatedVUs: 20 } },
  thresholds: { 'http_req_duration{kind:floor}': ['p(95)<300'] },
};

export function setup() {
  login();
  const ops = get('/mfg/floor/queue?limit=200', 'floor queue').json('items') || [];
  return { ops };
}

export default function (d) {
  if (!d.ops.length) { get('/mfg/floor/scan?code=KB:none', 'scan'); return; }
  const op = pick(d.ops);
  const kind = pick(['start', 'report', 'complete', 'scan']);
  const eventType = { start: 'start', report: 'report', complete: 'complete' }[kind];
  if (kind === 'scan') { get(`/mfg/floor/scan?code=${encodeURIComponent(op.wo_number || 'WO')}`, 'scan'); return; }
  const body = { wo_operation_id: op.id || op.wo_operation_id, event_type: eventType,
    client_event_id: `k6-${__VU}-${__ITER}-${Date.now()}` };
  if (kind !== 'start') body.qty_good = 1;
  const r = http.post(`${API}/mfg/floor/events`, JSON.stringify(body), { headers: headers(), tags: { kind: 'floor' } });
  check(r, { 'event accepted': (x) => x.status < 500 });
}
