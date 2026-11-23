/**
 * Smaller phone screens (M6 2): work order quick view, scan (keyboard wedge; camera through `BarcodeDetector` where
 * the browser has it, else typing), More (notifications opt-in, assistant, desktop, theme) and the assistant.
 */
import { formatDay } from "../../lib/locale";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Icon } from "../../components/Icon";
import { ALL_TOPICS, forgetPush, pushAvailableOnServer, pushSupport, PUSH_SUPPORT_TEXT, storedPush, subscribePush, TOPIC_TEXT, unsubscribePush, type StoredPush } from "../../pwa/pwa";
import { getWorkOrder } from "../api/clientM2";
import { floorScan, listWoOperationsM4 } from "../api/clientM4";
import { listPushSubscriptions } from "../api/clientM6";
import type { PushTopic } from "../api/typesM6";
import { AssistantBody } from "../assistant/AssistantPanel";
import { MfgError, Spinner } from "../components/Feedback";
import { OpStatusChip } from "../floor/floorText";
import { useAccess, useCan } from "../lib/permissions";
import { useAuth } from "../../auth/AuthContext";
import { errorText, useLoad } from "../lib/useMfg";
import { mobileLink } from "./MobileAlerts";
import { t, t as tr } from "../../lib/i18n";

// ---------------------------------------------------------------- work order quick view
export function MobileWo() {
  const { woId = "" } = useParams();
  const wo = useLoad((signal) => getWorkOrder(woId, signal), [woId]);
  const ops = useLoad((signal) => listWoOperationsM4(woId, signal).catch(() => null), [woId]);
  const w = wo.data;
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-wo">
      {wo.error && !w ? <MfgError error={wo.error} onRetry={wo.reload} /> : null}
      {wo.loading && !w ? <Spinner /> : null}
      {w ? (
        <>
          <h1>{w.number}</h1>
          <section className="m-card">
            <dl className="m-dl">
              <dt>{t("mobile.mobileMisc.head.item")}</dt>
              <dd>
                {w.item.part_number} {w.item.description ? <span className="muted">{w.item.description}</span> : null}
              </dd>
              <dt>{t("mobile.mobileMisc.head.status")}</dt>
              <dd>{w.status.replace(/_/g, " ")}</dd>
              <dt>{t("mobile.mobileMisc.head.quantity")}</dt>
              <dd>
                {tr("mobile.mobileMisc.text.done", { tr: tr("common.nOfM", { n: w.qty_completed, m: w.qty }), v: w.qty_scrapped ? `, ${w.qty_scrapped} scrapped` : "" })}
              </dd>
              <dt>{t("mobile.mobileMisc.head.due")}</dt>
              <dd>{formatDay(w.due_date)}</dd>
              {w.demand_line ? (
                <>
                  <dt>{t("mobile.mobileMisc.head.for")}</dt>
                  <dd>
                    {w.demand_line.order_number}/{w.demand_line.line_no}
                  </dd>
                </>
              ) : null}
              {w.shortage_count ? (
                <>
                  <dt>{t("mobile.mobileMisc.head.shortages")}</dt>
                  <dd className="m-state">
                    <Icon name="alert" size={14} />{" "}{tr("mobile.mobileMisc.text.componentsShort", { shortagecount: w.shortage_count })}
                  </dd>
                </>
              ) : null}
            </dl>
          </section>
          {ops.data?.items.length ? (
            <section className="m-card" aria-labelledby="m-wo-ops">
              <h2 id="m-wo-ops">{t("mobile.mobileMisc.head.operations")}</h2>
              <ul className="m-list">
                {ops.data.items.map((o) => (
                  <li key={o.id} className="m-row">
                    <div className="grow">
                      <strong>{o.seq}</strong> {o.name}
                      <div className="m-sub">
                        {o.line?.code ?? o.group?.code ?? ""} · {o.qty_good}/{o.qty_planned}
                      </div>
                    </div>
                    <OpStatusChip status={o.status} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <Link to={`/mfg/work-orders/${encodeURIComponent(w.id)}`} className="btn ghost">
            {tr("mobile.mobileMisc.text.openOnTheFullSite")}{" "}<Icon name="external" />
          </Link>
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- scan
type Detector = { detect(src: CanvasImageSource): Promise<{ rawValue: string }[]> };
type DetectorCtor = new (opts?: { formats?: string[] }) => Detector;

function scanTarget(type: string, id: string, link: string, ctx: Record<string, unknown>): string {
  if (type === "line") return `/m/lines/${encodeURIComponent(id)}`;
  if (type === "work_order") return `/m/wo/${encodeURIComponent(id)}`;
  if (type === "operation" && typeof ctx.wo_id === "string") return `/m/wo/${encodeURIComponent(ctx.wo_id)}`;
  return mobileLink(link) ?? "/m";
}

export function MobileScan() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const Ctor = (globalThis as unknown as { BarcodeDetector?: DetectorCtor }).BarcodeDetector;

  const resolve = async (raw: string) => {
    const c = raw.trim();
    if (!c) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await floorScan(c);
      navigate(scanTarget(r.type, r.id, r.link, r.context ?? {}));
    } catch (e) {
      setErr(errorText(e));
      input.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    input.current?.focus();
  }, []);

  useEffect(() => {
    if (!camera || !Ctor) return;
    let stream: MediaStream | null = null;
    let stop = false;
    const det = new Ctor({ formats: ["code_128", "qr_code", "data_matrix", "ean_13", "code_39"] });
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        while (!stop && video.current) {
          const found = await det.detect(video.current).catch(() => []);
          if (found[0]?.rawValue) {
            stop = true;
            setCamera(false);
            setCode(found[0].rawValue);
            void resolve(found[0].rawValue);
            break;
          }
          await new Promise((r) => setTimeout(r, 250));
        }
      } catch {
        setErr(tr("mobile.mobileMisc.str.theCameraCouldNotBe"));
        setCamera(false);
      }
    })();
    return () => {
      stop = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera]);

  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-scan">
      <h1>{t("mobile.mobileMisc.head.scan")}</h1>
      <form
        className="col"
        style={{ gap: 8 }}
        onSubmit={(e) => {
          e.preventDefault();
          void resolve(code);
        }}
      >
        <label htmlFor="m-scan-code" style={{ fontWeight: 600 }}>
          {tr("mobile.mobileMisc.text.codeWorkOrderOperationLine")}
        </label>
        <input
          id="m-scan-code"
          ref={input}
          className="input m-scan-input"
          autoComplete="off"
          autoCapitalize="characters"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder={t("mobile.mobileMisc.ph.scanOrTypeThenEnter")}
          data-testid="m-scan-input"
        />
        <div className="m-actions">
          <button type="submit" className="btn primary" disabled={busy || !code.trim()}>
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}{" "}{tr("mobile.mobileMisc.text.open")}
          </button>
          {Ctor ? (
            <button type="button" className="btn" onClick={() => setCamera((v) => !v)} aria-pressed={camera} data-testid="m-scan-camera">
              <Icon name={camera ? "stop" : "zoom-in"} /> {camera ? tr("mobile.mobileMisc.str.stopCamera") : tr("mobile.mobileMisc.str.useTheCamera")}
            </button>
          ) : (
            <span className="muted small">{tr("mobile.mobileMisc.text.thisBrowserCannotReadCodes")}</span>
          )}
        </div>
      </form>
      {camera ? <video ref={video} className="m-video" muted playsInline aria-label={t("mobile.mobileMisc.aria.cameraPreview")} /> : null}
      {err ? (
        <p className="field-error" role="alert" style={{ margin: 0 }} data-testid="m-scan-error">
          {err}
        </p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- notifications (push opt-in)
function PushSettings() {
  const server = useLoad((signal) => pushAvailableOnServer(signal), []);
  const auth = useAuth();
  const access = useAccess();
  const uid = auth.user?.id ?? access.me?.user_id ?? "";
  const [sub, setSub] = useState<StoredPush | null>(() => storedPush(uid));
  // the server drops subscriptions whose push service answers 404/410: then this phone is off again
  const mine = useLoad((signal) => (server.data?.available && sub ? listPushSubscriptions(signal).catch(() => null) : null), [server.data?.available, sub?.id]);
  useEffect(() => {
    if (sub && mine.data && !mine.data.items.some((x) => x.id === sub.id)) {
      forgetPush(uid);
      setSub(null);
    }
  }, [mine.data, sub]);
  const [topics, setTopics] = useState<PushTopic[]>(() => storedPush(uid)?.topics ?? ["critical_alerts", "approvals"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const support = pushSupport();

  if (server.loading && !server.data) return <Spinner label={t("mobile.mobileMisc.label.checkingNotifications")} />;
  if (server.error) return <MfgError error={server.error} onRetry={server.reload} />;
  if (!server.data?.available) {
    return (
      <p className="muted" style={{ margin: 0 }} data-testid="m-push-off">
        <Icon name="info" size={14} /> {t("mobile.mobileMisc.btn.pushNotificationsAreNotSet")}
      </p>
    );
  }
  if (!support.ok) {
    return (
      <p className="m-banner" style={{ margin: 0 }} data-testid="m-push-unsupported" data-reason={support.reason}>
        <Icon name="info" size={16} /> {PUSH_SUPPORT_TEXT[support.reason]}
      </p>
    );
  }
  const save = async (next: PushTopic[] | null) => {
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      if (next === null || next.length === 0) {
        await unsubscribePush(uid);
        setSub(null);
      } else {
        setSub(await subscribePush(uid, next, server.data!.key!));
      }
      setSaved(true);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col" style={{ gap: 8 }} data-testid="m-push">
      <span className="m-state" data-testid="m-push-state" data-on={Boolean(sub)}>
        <Icon name={sub ? "check" : "circle"} size={14} /> {sub ? tr("mobile.mobileMisc.str.notificationsAreOnForThis") : tr("mobile.mobileMisc.str.notificationsAreOffForThis")}
        {sub && mine.data?.items.find((x) => x.id === sub.id)?.active === false ? tr("mobile.mobileMisc.str.deliveriesStoppedWorkingTurnThem") : ""}
      </span>
      <fieldset className="mfg-fieldset">
        <legend>{t("mobile.mobileMisc.head.tellMeAbout")}</legend>
        {ALL_TOPICS.map((t) => (
          <label key={t} className="checkbox" style={{ alignItems: "flex-start", minHeight: 44 }}>
            <input
              type="checkbox"
              checked={topics.includes(t)}
              onChange={(e) => setTopics(e.target.checked ? [...topics, t] : topics.filter((x) => x !== t))}
              data-testid={`m-push-topic-${t}`}
            />
            <span>
              <strong>{TOPIC_TEXT[t].label}</strong>
              <br />
              <span className="muted small">{TOPIC_TEXT[t].help}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="m-actions">
        <button type="button" className="btn primary" disabled={busy || !topics.length} onClick={() => void save(topics)} data-testid="m-push-save">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {sub ? tr("mobile.mobileMisc.str.save") : tr("mobile.mobileMisc.str.turnOnNotifications")}
        </button>
        {sub ? (
          <button type="button" className="btn" disabled={busy} onClick={() => void save(null)} data-testid="m-push-off-btn">
            {t("mobile.mobileMisc.btn.turnOff")}
          </button>
        ) : null}
      </div>
      {saved ? <span role="status" className="small">{tr("mobile.mobileMisc.text.saved")}</span> : null}
      {err ? (
        <p className="field-error" role="alert" style={{ margin: 0 }} data-testid="m-push-error">
          {err}
        </p>
      ) : null}
      <span className="muted small">{tr("mobile.mobileMisc.text.messagesShowATitleAnd")}</span>
    </div>
  );
}

export function MobileMore() {
  const canAsk = useCan("view");
  const setTheme = (t: "light" | "dark") => {
    try {
      localStorage.setItem("sp.theme", JSON.stringify(t));
    } catch {
      /* ignore */
    }
    document.documentElement.setAttribute("data-theme", t);
  };
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-more">
      <h1>{t("mobile.mobileMisc.head.more")}</h1>
      <nav className="m-list" aria-label={t("mobile.mobileMisc.aria.more")}>
        <Link to="/m/scan" className="m-row">
          <Icon name="zoom-in" /> <span className="grow">{tr("mobile.mobileMisc.text.scanACode")}</span> <Icon name="chevron-right" />
        </Link>
        {canAsk ? (
          <Link to="/m/assistant" className="m-row" data-testid="m-more-assistant">
            <Icon name="help" /> <span className="grow">{tr("mobile.mobileMisc.text.planningAssistant")}</span> <Icon name="chevron-right" />
          </Link>
        ) : null}
        <Link to="/mfg/dashboard" className="m-row">
          <Icon name="graph" /> <span className="grow">{tr("mobile.mobileMisc.text.dashboard")}</span> <Icon name="chevron-right" />
        </Link>
        <Link to="/mfg" className="m-row">
          <Icon name="external" /> <span className="grow">{tr("mobile.mobileMisc.text.fullSite")}</span> <Icon name="chevron-right" />
        </Link>
      </nav>
      <section className="m-card" aria-labelledby="m-push-h">
        <h2 id="m-push-h">{t("mobile.mobileMisc.head.notifications")}</h2>
        <PushSettings />
      </section>
      <section className="m-card" aria-labelledby="m-theme-h">
        <h2 id="m-theme-h">{t("mobile.mobileMisc.head.appearance")}</h2>
        <div className="m-actions">
          <button type="button" className="btn" onClick={() => setTheme("light")}>
            <Icon name="sun" /> {t("mobile.mobileMisc.btn.light")}
          </button>
          <button type="button" className="btn" onClick={() => setTheme("dark")}>
            <Icon name="moon" /> {t("mobile.mobileMisc.btn.dark")}
          </button>
        </div>
      </section>
    </div>
  );
}

export function MobileAssistant() {
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-assistant">
      <h1>{t("mobile.mobileMisc.head.planningAssistant")}</h1>
      <p className="muted small" style={{ margin: 0 }}>
        {tr("mobile.mobileMisc.text.explainsYourPlanAndSuggests")}
      </p>
      <AssistantBody />
    </div>
  );
}
