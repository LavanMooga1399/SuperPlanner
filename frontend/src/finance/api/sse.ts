/**
 * Live finance run progress (FINANCE.md 19). Same algorithm as `src/api/sse.ts`:
 * one listener per named event, close on a terminal event, 204 -> status check,
 * polling fallback after 3 errors, de-duplication by `seq`.
 */
import { getFinanceRun, financeRunEventsUrl, listFinanceRunEvents } from "./client";
import {
  FIN_ACTIVE_STATUSES,
  FIN_EVENT_TYPES,
  FIN_TERMINAL_EVENTS,
  type FinanceRun,
  type FinRunEvent,
} from "./types";

export type FinStreamMode = "connecting" | "live" | "reconnecting" | "polling" | "closed";

export interface FinSubscribeOptions {
  afterSeq?: number;
  onModeChange?: (mode: FinStreamMode) => void;
  pollIntervalMs?: number;
}

export interface FinRunSubscription {
  close(): void;
}

export function subscribeFinanceRunEvents(
  runId: string,
  onEvent: (ev: FinRunEvent) => void,
  onEnd: (run: FinanceRun | null) => void,
  opts: FinSubscribeOptions = {},
): FinRunSubscription {
  let lastSeq = opts.afterSeq ?? 0;
  let closed = false;
  let errors = 0;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const pollMs = opts.pollIntervalMs ?? 1500;
  const setMode = (m: FinStreamMode) => opts.onModeChange?.(m);

  const finish = (run: FinanceRun | null) => {
    if (closed) return;
    closed = true;
    es?.close();
    es = null;
    if (pollTimer) clearTimeout(pollTimer);
    setMode("closed");
    onEnd(run);
  };

  const deliver = (ev: FinRunEvent): boolean => {
    if (closed) return true;
    if (typeof ev.seq === "number" && ev.seq <= lastSeq) return false;
    if (typeof ev.seq === "number") lastSeq = ev.seq;
    onEvent(ev);
    if (FIN_TERMINAL_EVENTS.includes(ev.type)) {
      es?.close();
      es = null;
      getFinanceRun(runId)
        .then((r) => finish(r))
        .catch(() => finish(null));
      return true;
    }
    return false;
  };

  const drain = async (): Promise<boolean> => {
    const { items } = await listFinanceRunEvents(runId, lastSeq);
    for (const ev of items.sort((a, b) => a.seq - b.seq)) {
      if (deliver(ev)) return true;
    }
    return false;
  };

  const poll = async () => {
    if (closed) return;
    try {
      if (await drain()) return;
      const run = await getFinanceRun(runId);
      if (!FIN_ACTIVE_STATUSES.includes(run.status)) {
        finish(run);
        return;
      }
    } catch {
      try {
        const run = await getFinanceRun(runId);
        if (!FIN_ACTIVE_STATUSES.includes(run.status)) {
          finish(run);
          return;
        }
      } catch {
        /* keep polling */
      }
    }
    if (!closed) pollTimer = setTimeout(poll, pollMs);
  };

  const startPolling = () => {
    es?.close();
    es = null;
    setMode("polling");
    void poll();
  };

  const connect = () => {
    if (closed) return;
    if (typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    const url = financeRunEventsUrl(runId) + (lastSeq > 0 ? `?after=${lastSeq}` : "");
    setMode("connecting");
    es = new EventSource(url);
    es.onopen = () => {
      errors = 0;
      setMode("live");
    };
    for (const type of FIN_EVENT_TYPES) {
      es.addEventListener(type, (msg: MessageEvent<string>) => {
        try {
          deliver(JSON.parse(msg.data) as FinRunEvent);
        } catch {
          /* ignore malformed frame */
        }
      });
    }
    es.onerror = () => {
      if (closed) return;
      errors += 1;
      if (es?.readyState === EventSource.CLOSED) {
        es = null;
        getFinanceRun(runId)
          .then(async (run) => {
            if (!FIN_ACTIVE_STATUSES.includes(run.status)) {
              try {
                if (await drain()) return;
              } catch {
                /* fall through */
              }
              finish(run);
              return;
            }
            if (errors >= 3) startPolling();
            else setTimeout(connect, 1000);
          })
          .catch(() => {
            if (errors >= 3) startPolling();
            else setTimeout(connect, 1500);
          });
        return;
      }
      if (errors >= 3) startPolling();
      else setMode("reconnecting");
    };
  };

  connect();

  return {
    close() {
      if (closed) return;
      closed = true;
      es?.close();
      es = null;
      if (pollTimer) clearTimeout(pollTimer);
    },
  };
}
