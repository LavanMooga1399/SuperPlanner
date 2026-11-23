/** QR code as SVG (M5 3.2 TOTP enrolment). Black on white with a quiet zone, whatever the theme. */
import { useMemo } from "react";
import { qrMatrix } from "../lib/qrcode";
import { t } from "../lib/i18n";

export function QrCode({ text, size = 200, label, testId }: { text: string; size?: number; label: string; testId?: string }) {
  const m = useMemo(() => {
    try {
      return qrMatrix(text);
    } catch {
      return null;
    }
  }, [text]);
  if (!m) return <span className="badge danger">{t("studio.qrCode.text.theCodeIsTooLong")}</span>;
  const q = 4;
  const n = m.length + q * 2;
  let d = "";
  m.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (dark) d += `M${x + q},${y + q}h1v1h-1z`;
    }),
  );
  return (
    <svg width={size} height={size} viewBox={`0 0 ${n} ${n}`} role="img" aria-label={label} shapeRendering="crispEdges" data-testid={testId} style={{ background: "#fff", borderRadius: 4 }}>
      <rect width={n} height={n} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}
