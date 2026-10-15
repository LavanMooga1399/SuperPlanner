/**
 * Live run progress (ARCHITECTURE 15, 17.3).
 *
 * - One `addEventListener` per named event type (frames carry `event:`, so
 *   `onmessage` would receive nothing).
 * - Closes itself on a terminal event.
 * - The server answers 204 for finished runs; EventSource then reports an
 *   error with readyState CLOSED, which we treat as "ended" after a status check.
 * - After 3 errors, falls back to polling every 2 s.
 * - Events are de-duplicated by `seq`, so replays after reconnects are harmless.
 */
import { getRun, listRunEvents, runEventsUrl } from "./client";
import {
  ACTIVE_RUN_STATUSES,
  RUN_EVENT_TYPES,
  TERMINAL_EVENT_TYPES,
  type RunEvent,
  type SolverRun,
} from "./types";

export type StreamMode = "connecting" | "live" | "reconnecting" | "polling" | "closed";

export interface SubscribeOptions {
  /** Last seq already seen; only later events are delivered. */
  afterSeq?: number;
  onModeChange?: (mode: StreamMode) => void;
  pollIntervalMs?: number;
}

export interface RunSubscription {
  close(): void;
}

export function subscribeRunEvents(
  runId: string,
  onEvent: (ev: RunEvent) => void,
  onEnd: (run: SolverRun | null) => void,
  opts: SubscribeOptions = {},
): RunSubscription {
  let lastSeq = opts.afterSeq ?? 0;
  let closed = false;
  let errors = 0;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const pollMs = opts.pollIntervalMs ?? 2000;

  const setMode = (m: StreamMode) => opts.onModeChange?.(m);

  const finish = (run: SolverRun | null) => {
    if (closed) return;
    closed = true;
    es?.close();
    es = null;
    if (pollTimer) clearTimeout(pollTimer);
    setMode("closed");
    onEnd(run);
  };

  const deliver = (ev: RunEvent): boolean => {
    if (typeof ev.seq === "number" && ev.seq <= lastSeq) return false;
    if (typeof ev.seq === "number") lastSeq = ev.seq;
    onEvent(ev);
    if (TERMINAL_EVENT_TYPES.includes(ev.type)) {
      // Fetch the final run summary for the caller, but stop streaming now.
      es?.close();
      es = null;
      getRun(runId)
        .then((r) => finish(r))
        .catch(() => finish(null));
      return true;
    }
    return false;
  };

  const poll = async () => {
    if (closed) return;
    try {
      const { items } = await listRunEvents(runId, lastSeq);
      for (const ev of items.sort((a, b) => a.seq - b.seq)) {
        if (deliver(ev)) return;
      }
      const run = await getRun(runId);
      if (!ACTIVE_RUN_STATUSES.includes(run.status)) {
        // Terminal without a terminal event seen (should not happen) -> end anyway.
        finish(run);
        return;
      }
    } catch {
      try {
        const run = await getRun(runId);
        if (!ACTIVE_RUN_STATUSES.includes(run.status)) {
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
    if (typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    const url = runEventsUrl(runId) + (lastSeq > 0 ? `?after=${lastSeq}` : "");
    setMode("connecting");
    es = new EventSource(url);
    es.onopen = () => {
      errors = 0;
      setMode("live");
    };
    for (const type of RUN_EVENT_TYPES) {
      es.addEventListener(type, (msg: MessageEvent<string>) => {
        try {
          const data = JSON.parse(msg.data) as RunEvent;
          deliver(data);
        } catch {
          /* ignore malformed frame */
        }
      });
    }
    es.onerror = () => {
      if (closed) return;
      errors += 1;
      const isClosed = es?.readyState === EventSource.CLOSED;
      if (isClosed) {
        // 204 (finished run) or a hard failure: check the run once.
        es = null;
        getRun(runId)
          .then((run) => {
            if (!ACTIVE_RUN_STATUSES.includes(run.status)) {
              // Pick up any events we missed, then end.
              return listRunEvents(runId, lastSeq)
                .then(({ items }) => {
                  for (const ev of items.sort((a, b) => a.seq - b.seq)) {
                    if (deliver(ev)) return;
                  }
                  finish(run);
                })
                .catch(() => finish(run));
            }
            if (errors >= 3) startPolling();
            else setTimeout(() => !closed && connect(), 1000);
            return undefined;
          })
          .catch(() => {
            if (errors >= 3) startPolling();
            else setTimeout(() => !closed && connect(), 1500);
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
