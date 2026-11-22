/** Bulk actions (docs/UX-STANDARD.md "Backend support"): `POST /mfg/bulk/{collection}/{action}`. */
import { mfgRequest } from "./client";
import { newIdempotencyKey } from "./clientM2";

export type BulkAction =
  | "work-orders/release"
  | "work-orders/close"
  | "work-orders/cancel"
  | "purchase-requests/submit"
  | "purchase-requests/approve"
  | "purchase-requests/reject"
  | "purchase-orders/cancel"
  | "demand-orders/close"
  | "demand-orders/cancel";

export interface BulkItemResult {
  id: string;
  ok: boolean;
  status: number;
  code: string | null;
  message: string | null;
  row_version: number | null;
  record_status: string | null;
  details: Record<string, unknown> | null;
}

export interface BulkResponse {
  action: string;
  total: number;
  succeeded: number;
  failed: number;
  results: BulkItemResult[];
}

/** One request per user confirmation; the idempotency key makes a network retry safe. */
export const runBulk = (action: BulkAction, items: { id: string; row_version: number }[], params: Record<string, unknown> = {}, key = newIdempotencyKey("bulk")) =>
  mfgRequest<BulkResponse>(`/bulk/${action}`, { method: "POST", body: { items, ...params }, headers: { "Idempotency-Key": key } });
