/** Money formatting (FINANCE.md 12, 20.2). INR uses the ₹ symbol and lakh/crore grouping. */

export interface MoneyOptions {
  /** "₹12.5 L", "₹1.2 Cr" for INR; Intl compact notation otherwise. */
  compact?: boolean;
  /** Show a leading "+" for positive values (deltas). */
  signed?: boolean;
  decimals?: number;
}

const cache = new Map<string, Intl.NumberFormat>();

function nf(locale: string, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = locale + JSON.stringify(opts);
  let f = cache.get(key);
  if (!f) {
    try {
      f = new Intl.NumberFormat(locale, opts);
    } catch {
      f = new Intl.NumberFormat("en-IN", { ...opts, style: "decimal" });
    }
    cache.set(key, f);
  }
  return f;
}

export function currencySymbol(currency: string, locale = "en-IN"): string {
  try {
    const part = nf(locale, { style: "currency", currency, currencyDisplay: "narrowSymbol" })
      .formatToParts(0)
      .find((p) => p.type === "currency");
    return part?.value ?? currency;
  } catch {
    return currency;
  }
}

export function formatMoney(
  amount: number | null | undefined,
  currency = "INR",
  locale = "en-IN",
  opts: MoneyOptions = {},
): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return "-";
  const sign = amount < 0 ? "-" : opts.signed && amount > 0 ? "+" : "";
  const abs = Math.abs(amount);
  const sym = currencySymbol(currency, locale);
  if (opts.compact) {
    if (currency === "INR") {
      if (abs >= 1e7) return `${sign}${sym}${trim(abs / 1e7)} Cr`;
      if (abs >= 1e5) return `${sign}${sym}${trim(abs / 1e5)} L`;
      if (abs >= 1e3) return `${sign}${sym}${trim(abs / 1e3)}K`;
      return `${sign}${sym}${Math.round(abs)}`;
    }
    return sign + nf(locale, { style: "currency", currency, notation: "compact", maximumFractionDigits: 1 }).format(abs);
  }
  const d = opts.decimals ?? 0;
  try {
    return (
      sign +
      nf(locale, { style: "currency", currency, currencyDisplay: "narrowSymbol", maximumFractionDigits: d, minimumFractionDigits: d }).format(abs)
    );
  } catch {
    return `${sign}${sym}${abs.toFixed(d)}`;
  }
}

function trim(v: number): string {
  const s = v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
  return s.replace(/\.?0+$/, "");
}

export function formatPct(v: number | null | undefined, decimals = 0, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "-";
  const s = v.toFixed(decimals);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

/** Probability 0..1 -> "74%". */
export function formatProb(p: number | null | undefined, signed = false): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "-";
  return formatPct(p * 100, 0, signed);
}

/** Display rounding for amounts (UI only, FINANCE.md 8.8): to 100 above 10,000. */
export function roundDisplay(v: number): number {
  if (Math.abs(v) >= 10000) return Math.round(v / 100) * 100;
  return Math.round(v);
}
