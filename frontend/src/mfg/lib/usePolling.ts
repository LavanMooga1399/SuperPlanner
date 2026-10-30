/** Re-run `fn` every `ms` while `active` (M3 12: running schedule runs are polled every 2 s). */
import { useEffect, useRef } from "react";

export function usePolling(fn: () => void, active: boolean, ms = 2000): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
  }, [active, ms]);
}
