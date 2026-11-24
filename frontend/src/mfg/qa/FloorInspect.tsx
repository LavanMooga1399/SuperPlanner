/**
 * `/mfg/floor/inspect/:lotId` (M7 10, tablet): results entry on the shop floor. Characteristic cards with their
 * progress and live verdict, the sample grid, a numeric pad for measured values or big Pass / Fail buttons, and the
 * gauge field (scan `E:<code>` or choose; the calibration state is shown and invalid gauges are refused). Results are
 * sent per sample with a `client_batch_id`; without a connection they wait on the device and are replayed in order.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { getInspectionLot, listEquipment } from "../api/clientM7";
import type { Equipment, ResultEntry } from "../api/typesM7";
import { MfgError, Spinner } from "../components/Feedback";
import { useScanHandler } from "../floor/FloorLayout";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { errorText } from "../lib/useMfg";
import { formatNumber } from "../../lib/locale";
import { plural, t } from "../../lib/i18n";
import { batchId } from "./common";
import { CalChip, LotStatusChip, VerdictChip } from "./labels";
import { useGauges } from "./InspectionPages";
import { charStates, isDefective, nextOpenSample, submitResults, useResultQueue } from "./results";
import "./qa.css";

/** the decimal separator of the UI language ("." or ",") */
const DEC = formatNumber(1.5).charAt(1);
const PAD = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "back"];

export function FloorInspect() {
  const { lotId = "" } = useParams();
  const canInspect = useCan("qa_inspect");
  const rec = useLoad((s) => getInspectionLot(lotId, s), [lotId]);
  const lot = rec.data;
  const states = useMemo(() => (lot ? charStates(lot) : []), [lot]);
  const [charId, setCharId] = useState<string>("");
  const [sample, setSample] = useState<number | null>(null);
  const [entry, setEntry] = useState("");
  const [gauge, setGauge] = useState<Equipment | null>(null);
  const [scan, setScan] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const queued = useResultQueue(lotId);
  const s = states.find((x) => x.c.id === charId) ?? states[0] ?? null;
  const gauges = useGauges(s?.c.equipment_class ?? null);
  useEffect(() => {
    if (lot) document.title = `${lot.number} - ${t("qa.fi.str.title")}`;
  }, [lot]);
  useEffect(() => {
    if (s && sample === null) setSample(nextOpenSample(s));
  }, [s, sample]);
  useEffect(() => {
    // a gauge of another class does not carry over to the next characteristic
    if (gauge && s && gauge.equipment_class !== s.c.equipment_class) setGauge(null);
  }, [s, gauge]);

  const resolveGauge = async (raw: string) => {
    const code = raw.trim().replace(/^E:/i, "");
    if (!code) return;
    setError(null);
    try {
      const page = await listEquipment({ q: code, limit: 5 });
      const hit = page.items.find((e) => e.code.toLowerCase() === code.toLowerCase()) ?? null;
      if (!hit) return setError(t("qa.fi.err.unknownGauge", { code }));
      if (s?.c.equipment_class && hit.equipment_class !== s.c.equipment_class) return setError(t("qa.fi.err.wrongClass", { code: hit.code, cls: s.c.equipment_class }));
      setGauge(hit);
      setScan("");
    } catch (e) {
      setError(errorText(e));
    }
  };
  useScanHandler(
    (code) => {
      if (/^E:/i.test(code)) {
        void resolveGauge(code);
        return true;
      }
      return false;
    },
    [s?.c.id],
  );

  if (rec.loading && !lot) return <Spinner />;
  if (!lot) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const open = ["open", "in_progress", "ready"].includes(lot.status);
  const editable = open && canInspect && s !== null;
  const c = s?.c;

  const send = async (passed?: boolean) => {
    if (!s || !c || sample === null || busy) return;
    let value: number | null = null;
    if (c.kind === "variable") {
      value = Number(entry);
      if (!entry || !Number.isFinite(value)) return;
    }
    if (c.equipment_class && !gauge) return setError(t("qa.lots.err.gauge", { cls: c.equipment_class }));
    if (gauge && !gauge.valid) return setError(t("qa.fi.err.invalidGauge", { code: gauge.code }));
    const r: ResultEntry = { characteristic_id: c.id, sample_no: sample, ...(c.kind === "variable" ? { value } : { passed: Boolean(passed), defects: passed ? 0 : 1 }), ...(gauge ? { equipment_id: gauge.id } : {}) };
    setBusy(true);
    setError(null);
    try {
      const out = await submitResults(lot.id, batchId(lot.number), [r]);
      const bad = isDefective(c, { value, passed: c.kind === "variable" ? true : Boolean(passed) });
      setFlash(out.status === "queued" ? t("qa.fi.str.savedOffline", { n: sample }) : bad ? t("qa.fi.str.savedBad", { n: sample }) : t("qa.fi.str.saved", { n: sample }));
      window.setTimeout(() => setFlash(null), 2500);
      setEntry("");
      // next open sample of the same characteristic (locally, before the reload)
      let nx: number | null = null;
      for (let i = sample + 1; i <= s.n; i++) if (!s.bySample.has(i)) {
        nx = i;
        break;
      }
      setSample(nx);
      rec.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const press = (k: string) => {
    if (k === "back") setEntry((x) => x.slice(0, -1));
    else if (k === ".") setEntry((x) => (x.includes(".") ? x : `${x || "0"}.`));
    else setEntry((x) => (x.length >= 12 ? x : x + k));
  };

  return (
    <div className="fi" data-testid="qa-floor-inspect">
      <div className="fi-head">
        <div>
          <Link to={mfgPaths.floor()} className="small">
            {t("qa.fi.btn.back")}
          </Link>
          <h1 style={{ margin: "4px 0 0" }}>
            <span className="mono">{lot.number}</span> {lot.item ? <span>{lot.item.part_number}</span> : null}
          </h1>
          <div className="row wrap" style={{ gap: 8 }}>
            <LotStatusChip s={lot.status} />
            {lot.lot_code ? <span className="mono">{t("qa.fi.tpl.lot", { lot: lot.lot_code })}</span> : null}
            <span className="muted">{t("qa.fi.tpl.size", { n: formatNumber(lot.lot_size) })}</span>
          </div>
        </div>
        <div>
          <VerdictChip s={lot.verdict?.verdict ?? "pending"} testId="qa-verdict" />
        </div>
      </div>
      {queued.length ? (
        <Banner tone="warn" icon="refresh" title={t("qa.lots.title.queued")}>
          {t("qa.lots.tpl.queued", { n: plural(queued.length, t("qa.lots.str.batch"), t("qa.lots.str.batches")) })}
        </Banner>
      ) : null}
      {!open ? <Banner tone="info">{t("qa.fi.text.closed")}</Banner> : null}
      <div className="fi-chars" role="tablist" aria-label={t("qa.fi.aria.chars")}>
        {states.map((x) => (
          <button
            key={x.c.id}
            type="button"
            role="tab"
            aria-selected={x === s}
            aria-current={x === s ? "true" : undefined}
            className="fi-char"
            onClick={() => {
              setCharId(x.c.id);
              setSample(nextOpenSample(x));
              setEntry("");
            }}
          >
            <span className="row" style={{ justifyContent: "space-between", gap: 8 }}>
              <strong className="mono">{x.c.code}</strong>
              <VerdictChip s={x.verdict} />
            </span>
            <span className="small">{x.c.name}</span>
            <span className={`qa-progress${x.verdict === "accept" ? " ok" : x.verdict === "reject" ? " danger" : ""}`} aria-hidden>
              <span style={{ width: `${x.n ? Math.round((Math.min(x.entered, x.n) / x.n) * 100) : 0}%` }} />
            </span>
            <span className="small muted">{t("qa.lots.tpl.counts", { e: x.entered, n: x.n, d: x.defective })}</span>
          </button>
        ))}
      </div>
      {s && c ? (
        <div className="fi-body">
          <section className="card">
            <div className="card-header">
              <h2>
                <span className="mono">{c.code}</span> {c.name}
              </h2>
              <span className="small muted">{t("qa.lots.tpl.sampling", { n: s.n, ac: s.ac, re: s.re })}</span>
            </div>
            <div className="card-body col">
              <span className="qa-limits">
                {c.kind === "attribute" ? t("qa.lots.str.passFail") : [c.lsl !== null ? t("qa.lots.tpl.min", { v: formatNumber(c.lsl) }) : "", c.nominal !== null ? t("qa.lots.tpl.nominal", { v: formatNumber(c.nominal) }) : "", c.usl !== null ? t("qa.lots.tpl.max", { v: formatNumber(c.usl) }) : ""].filter(Boolean).join(" · ") + (c.unit ? ` ${c.unit}` : "")}
                {c.method ? ` · ${c.method}` : ""}
              </span>
              <div className="fi-samples" role="group" aria-label={t("qa.lots.tpl.samplesOf", { code: c.code })}>
                {Array.from({ length: s.n }, (_, i) => i + 1).map((n) => {
                  const r = s.bySample.get(n);
                  const bad = r ? isDefective(c, r) : false;
                  return (
                    <button
                      key={n}
                      type="button"
                      className={`qa-sample${r ? (bad ? " bad" : " good") : ""}`}
                      aria-pressed={sample === n}
                      disabled={Boolean(r) || !editable}
                      onClick={() => setSample(n)}
                      data-testid="qa-result-cell"
                      aria-label={r ? t("qa.lots.tpl.cellDone", { n, v: r.value !== null ? formatNumber(r.value) : r.passed ? t("qa.lots.str.pass") : t("qa.lots.str.fail"), state: bad ? t("qa.lots.str.defective") : t("qa.lots.str.ok") }) : t("qa.lots.tpl.cellOpen", { n })}
                    >
                      <span className="qa-sample-no">{n}</span>
                      <span className="qa-sample-val">
                        {r ? (
                          <>
                            <Icon name={bad ? "x" : "check"} size={12} />
                            {r.value !== null ? formatNumber(r.value) : r.passed ? t("qa.lots.str.pass") : t("qa.lots.str.fail")}
                          </>
                        ) : (
                          <span className="faint">—</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="small muted" style={{ margin: 0 }}>
                {t("qa.fi.text.correct")}
              </p>
            </div>
          </section>
          <section className="card" aria-live="polite">
            <div className="card-header">
              <h2>{sample !== null ? t("qa.fi.tpl.sample", { n: sample, m: s.n }) : t("qa.fi.str.allEntered")}</h2>
            </div>
            <div className="card-body col">
              {c.equipment_class ? (
                <div className="col" style={{ gap: 6 }}>
                  <form
                    className="fi-gauge"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void resolveGauge(scan);
                    }}
                  >
                    <div className="field grow">
                      <label htmlFor="fi-gauge">{t("qa.fi.label.gauge", { cls: c.equipment_class })}</label>
                      <input id="fi-gauge" className="input" value={scan} onChange={(e) => setScan(e.target.value)} placeholder={t("qa.fi.ph.gauge")} autoComplete="off" data-testid="qa-gauge-scan" />
                    </div>
                    <button type="submit" className="btn">
                      {t("qa.fi.btn.use")}
                    </button>
                  </form>
                  <div className="row wrap fi-gauges" style={{ gap: 6 }}>
                    {(gauges.data ?? []).map((g) => (
                      <button key={g.id} type="button" className="btn sm" aria-pressed={gauge?.id === g.id} disabled={!g.valid} onClick={() => setGauge(g)} title={g.valid ? undefined : t("qa.lots.str.notCalibrated")}>
                        <span className="mono">{g.code}</span>
                      </button>
                    ))}
                  </div>
                  {gauge ? (
                    <div className="row" style={{ gap: 8 }}>
                      <span>
                        <span className="mono">{gauge.code}</span> {gauge.name}
                      </span>
                      <CalChip state={gauge.due_state} valid={gauge.valid} due={gauge.due_on} />
                    </div>
                  ) : null}
                </div>
              ) : null}
              {sample !== null && editable ? (
                c.kind === "variable" ? (
                  <>
                    <div className="fi-display" data-testid="qa-fi-display" aria-label={t("qa.fi.aria.value")}>
                      {entry ? entry.replace(".", DEC) : <span className="faint">0</span>}
                      {c.unit ? <span className="muted" style={{ fontSize: 18, marginLeft: 8 }}>{c.unit}</span> : null}
                    </div>
                    <div className="fi-pad">
                      {PAD.map((k) => (
                        <button key={k} type="button" className="btn" onClick={() => press(k)} aria-label={k === "back" ? t("qa.fi.aria.back") : k}>
                          {k === "back" ? <Icon name="x" /> : k === "." ? DEC : k}
                        </button>
                      ))}
                    </div>
                    <button type="button" className="btn primary floor-action" style={{ minHeight: 56, fontSize: 18 }} disabled={busy || !entry} onClick={() => void send()} data-testid="qa-fi-save">
                      <Icon name="check" /> {t("qa.fi.btn.save")}
                    </button>
                  </>
                ) : (
                  <div className="fi-passfail">
                    <button type="button" className="btn" disabled={busy} onClick={() => void send(true)} data-testid="qa-pass">
                      <Icon name="check" /> {t("qa.lots.str.pass")}
                    </button>
                    <button type="button" className="btn danger" disabled={busy} onClick={() => void send(false)} data-testid="qa-fail">
                      <Icon name="x" /> {t("qa.lots.str.fail")}
                    </button>
                  </div>
                )
              ) : null}
              {flash ? (
                <p className="floor-flash" role="status" style={{ margin: 0 }}>
                  {flash}
                </p>
              ) : null}
              {error ? (
                <p className="field-error" role="alert" style={{ margin: 0 }}>
                  <Icon name="alert" size={14} /> {error}
                </p>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
