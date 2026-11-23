import { Icon } from "../../components/Icon";
import { fmtDate } from "../lib/format";
import { t } from "../../lib/i18n";

/** "From 1 Dec 2026 until 1 Mar 2027" (`to` exclusive), plus a serial range when set. */
export function effectivityText(
  from: string | null,
  to: string | null,
  serialFrom?: number | null,
  serialTo?: number | null,
): string {
  let s: string;
  if (!from && !to) s = t("mfg.effectivityBadge.str.always");
  else if (from && !to) s = t("mfg.effectivityBadge.tpl.from", { from: fmtDate(from) });
  else if (!from && to) s = t("mfg.effectivityBadge.tpl.until", { to: fmtDate(to) });
  else s = `${fmtDate(from)} to ${fmtDate(to)}`;
  if (serialFrom !== null && serialFrom !== undefined) s += `, units ${serialFrom}-${serialTo ?? serialFrom}`;
  return s;
}

export function EffectivityBadge(props: {
  from: string | null;
  to: string | null;
  serialFrom?: number | null;
  serialTo?: number | null;
}) {
  return (
    <span className="chip" title={props.to ? t("mfg.effectivityBadge.str.theEndDateIsExclusive") : undefined}>
      <Icon name="calendar" size={12} />
      {effectivityText(props.from, props.to, props.serialFrom, props.serialTo)}
    </span>
  );
}
