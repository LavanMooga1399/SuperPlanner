/**
 * After a purchase receipt (M7 5.2): the inspection lots the receipt created (incoming plans), linked, so the
 * receiver sees at once that the material is on inspection hold and who inspects it next. Uses
 * `posting.inspection_lots` when the server sends it, else looks the received lot codes up in the inspection worklist.
 */
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { listInspectionLots } from "../api/clientM7";
import type { PostingRecord } from "../api/typesM2";
import type { InspectionLot } from "../api/typesM7";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { t } from "../../lib/i18n";

export function ReceiptInspectionLots({ posting }: { posting: PostingRecord }) {
  const direct = (posting as PostingRecord & { inspection_lots?: { id: string; number: string }[] }).inspection_lots;
  const codes = [...new Set(posting.lines.map((l) => l.lot?.lot_code).filter((x): x is string => Boolean(x)))];
  const found = useLoad(
    (s) =>
      direct || !codes.length
        ? null
        : Promise.all(codes.map((c) => listInspectionLots({ q: c, status: "open,in_progress,ready", limit: 5 }, s).then((p) => p.items.filter((l: InspectionLot) => l.lot_code === c)).catch(() => [] as InspectionLot[]))).then((x) => x.flat()),
    [posting.id],
  );
  const lots = direct ?? (found.data ?? []).map((l) => ({ id: l.id, number: l.number }));
  if (!lots.length) return null;
  return (
    <Banner tone="info" icon="eye" title={t("qa.receipt.title")} testId="receipt-inspection-lots">
      {t("qa.receipt.text")}{" "}
      {lots.map((l, i) => (
        <span key={l.id}>
          {i ? ", " : ""}
          <Link to={mfgPaths.qaLot(l.id)} className="mono">
            {l.number}
          </Link>
        </span>
      ))}
    </Banner>
  );
}
