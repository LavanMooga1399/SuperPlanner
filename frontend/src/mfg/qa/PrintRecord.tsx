/**
 * `/mfg/print/qa/:type/:id` (M7 4.5, 10): the Part 11 package of one record rendered for printing or "save as PDF":
 * the record's fields, its signature manifestations, the audit trail with old and new values and reasons, the
 * attachment list with SHA-256, and the package fingerprint.
 */
import { useEffect } from "react";
import { useParams } from "react-router";
import { Icon } from "../../components/Icon";
import { getPart11Package } from "../api/clientM7";
import { MfgError, Spinner } from "../components/Feedback";
import { fmtBytes } from "../lib/importMapping";
import { useLoad } from "../lib/useMfg";
import { formatDateTime } from "../../lib/locale";
import { t } from "../../lib/i18n";
import { usePersonName } from "./common";
import { manifestText, recordTypeText } from "./labels";
import "./qa.css";

function scalar(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? t("qa.shell.str.yes") : t("qa.shell.str.no");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const HIDDEN = new Set(["signatures", "links", "attachments", "row_version"]);

export function PrintRecordPage() {
  const { type = "", id = "" } = useParams();
  const person = usePersonName();
  const pkg = useLoad((s) => getPart11Package(type, id, s), [type, id]);
  const p = pkg.data;
  const number = p ? String(p.record.number ?? p.record.code ?? p.record_id) : "";
  useEffect(() => {
    if (p) document.title = `${recordTypeText(p.record_type)} ${number}`;
  }, [p, number]);
  if (pkg.loading && !p) return <Spinner />;
  if (!p) return <MfgError error={pkg.error} onRetry={pkg.reload} />;
  const fields = Object.entries(p.record).filter(([k, v]) => !HIDDEN.has(k) && (typeof v !== "object" || v === null));
  const lists = Object.entries(p.record).filter(([k, v]) => !HIDDEN.has(k) && Array.isArray(v) && v.length && typeof v[0] === "object") as [string, Record<string, unknown>[]][];
  return (
    <article className="col gap-lg print-page qa-print" data-testid="qa-print">
      <div className="row no-print" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn primary" onClick={() => window.print()}>
          <Icon name="file" /> {t("qa.print.btn.print")}
        </button>
      </div>
      <header>
        <h1 style={{ margin: 0 }}>
          {recordTypeText(p.record_type)} <span className="mono">{number}</span>
        </h1>
        <p className="small muted" style={{ margin: "4px 0 0" }}>
          {t("qa.print.tpl.generated", { when: formatDateTime(p.generated_at), who: person(p.generated_by) })}
        </p>
        <p className="small" style={{ margin: "2px 0 0" }}>
          {t("qa.print.label.package")} <code className="esig-hash">{p.package_sha256}</code>
        </p>
      </header>
      <section>
        <h2>{t("qa.print.head.record")}</h2>
        <table className="table qa-print-table">
          <tbody>
            {fields.map(([k, v]) => (
              <tr key={k}>
                <th scope="row" style={{ width: "30%" }}>
                  {k.replace(/_/g, " ")}
                </th>
                <td>{scalar(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {lists.map(([k, rows]) => {
        const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((x) => x !== "id" && x !== "row_version").slice(0, 10);
        return (
          <section key={k}>
            <h2>{k.replace(/_/g, " ")}</h2>
            <table className="table qa-print-table">
              <thead>
                <tr>
                  {keys.map((c) => (
                    <th key={c}>{c.replace(/_/g, " ")}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    {keys.map((c) => (
                      <td key={c}>{scalar(r[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
      <section>
        <h2>{t("qa.sig.head.title")}</h2>
        {p.signatures.length ? (
          <ol className="qa-print-list">
            {p.signatures.map((s) => (
              <li key={s.id} data-testid="esig-manifest">
                {manifestText(s)}
                {s.comment ? <span className="muted">{` · ${s.comment}`}</span> : null}
                {s.status === "superseded" ? <span className="muted">{` · ${t("qa.sig.str.superseded")}`}</span> : null}
                {!s.content_matches_current ? <strong>{` · ${t("qa.sig.str.changedSince")}`}</strong> : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">{t("qa.sig.empty")}</p>
        )}
      </section>
      <section>
        <h2>{t("qa.history.head.title")}</h2>
        <table className="table qa-print-table">
          <thead>
            <tr>
              <th style={{ width: 150 }}>{t("qa.print.head.when")}</th>
              <th style={{ width: 150 }}>{t("qa.print.head.who")}</th>
              <th style={{ width: 120 }}>{t("qa.print.head.action")}</th>
              <th>{t("qa.print.head.changes")}</th>
            </tr>
          </thead>
          <tbody>
            {p.audit.map((e) => (
              <tr key={e.id}>
                <td>{formatDateTime(e.at)}</td>
                <td>{e.actor_name ?? e.actor_id ?? t("qa.history.str.system")}</td>
                <td>{e.action}</td>
                <td>
                  {e.changes.map((c, i) => (
                    <div key={i}>
                      <span className="mono">{c.path}</span>: {scalar(c.old)} → {scalar(c.new)}
                    </div>
                  ))}
                  {e.reason ? (
                    <div>
                      <b>{t("qa.history.label.reason")}</b> {e.reason}
                    </div>
                  ) : null}
                  {e.signature ? <div>{manifestText(e.signature)}</div> : null}
                </td>
              </tr>
            ))}
            {!p.audit.length ? (
              <tr>
                <td colSpan={4} className="muted">
                  {t("qa.history.empty")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
      <section>
        <h2>{t("qa.att.head.title")}</h2>
        {p.attachments.length ? (
          <table className="table qa-print-table">
            <thead>
              <tr>
                <th>{t("qa.att.head.file")}</th>
                <th className="num">{t("qa.att.head.size")}</th>
                <th>{t("qa.att.head.sha")}</th>
              </tr>
            </thead>
            <tbody>
              {p.attachments.map((a) => (
                <tr key={a.id}>
                  <td>{a.filename}</td>
                  <td className="num">{fmtBytes(a.size)}</td>
                  <td className="mono small">{a.sha256}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">{t("qa.att.empty")}</p>
        )}
      </section>
    </article>
  );
}
