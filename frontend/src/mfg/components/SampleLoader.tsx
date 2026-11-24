/** Sample dataset cards (M 11.1 `/mfg`): "Load" upserts, "Replace my data" resets first (confirmed). */
import { useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { listSamples, loadSample } from "../api/client";
import type { SampleInfo, SampleLoadResponse } from "../api/types";
import { useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";
import { t } from "../../lib/i18n";
import { LOCALE } from "../../lib/locale";

const COUNT_LABELS: Record<string, string> = {
  items: "items",
  bom_lines: t("mfg.sampleLoader.str.bomLines"),
  boms: "BOMs",
  routings: "routings",
  operations: "operations",
  groups: "stages",
  lines: "lines",
  operators: "operators",
};

function countsLine(counts: Record<string, number>): string {
  return Object.entries(counts)
    .filter(([k]) => COUNT_LABELS[k])
    .slice(0, 4)
    .map(([k, v]) => `${v.toLocaleString(LOCALE)} ${COUNT_LABELS[k]}`)
    .join(" · ");
}

export function SampleLoader({ onLoaded }: { onLoaded(res: SampleLoadResponse): void }) {
  const samples = useLoad((signal) => listSamples(signal), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirm, setConfirm] = useState<SampleInfo | null>(null);

  const run = async (s: SampleInfo, replace: boolean) => {
    setBusy(s.id);
    setError(null);
    try {
      const res = await loadSample(s.id, replace);
      onLoaded(res);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  return (
    <section className="col" aria-labelledby="mfg-samples-title">
      <div className="section-title">
        <Icon name="book" />
        <h2 id="mfg-samples-title">{t("mfg.sampleLoader.head.sampleData")}</h2>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {t("mfg.sampleLoader.text.fictionalReadyToUsePlants")}
      </p>
      <MfgError error={samples.error} onRetry={samples.reload} />
      <MfgError error={error} title={t("mfg.sampleLoader.attr.theSampleCouldNotBe")} />
      <div className="grid-3">
        {(samples.data?.items ?? []).map((s) => (
          <div className="card template-card" key={s.id} data-testid={`sample-card-${s.id}`}>
            <div className="card-body">
              <div className="row">
                <span className="template-icon" aria-hidden>
                  <Icon name="factory" />
                </span>
                <h3 className="grow">{s.name}</h3>
              </div>
              <p className="muted small" style={{ margin: 0 }}>
                {s.description}
              </p>
              <p className="faint small" style={{ margin: 0 }}>
                {countsLine(s.counts)}
              </p>
              <div className="row wrap" style={{ marginTop: "auto" }}>
                <button
                  type="button"
                  className="btn primary sm"
                  disabled={busy !== null}
                  onClick={() => void run(s, false)}
                  data-testid={`sample-load-${s.id}`}
                >
                  {busy === s.id ? <span className="spinner" aria-hidden /> : <Icon name="download" />}
                  {t("mfg.sampleLoader.text.load")}
                </button>
                <button
                  type="button"
                  className="btn sm"
                  disabled={busy !== null}
                  onClick={() => setConfirm(s)}
                  data-testid={`sample-replace-${s.id}`}
                >
                  <Icon name="refresh" /> {t("mfg.sampleLoader.btn.replaceMyData")}
                </button>
              </div>
            </div>
          </div>
        ))}
        {samples.loading && !samples.data ? (
          <div className="empty" role="status">
            <span className="spinner" aria-hidden />{" "}{t("mfg.sampleLoader.text.loadingSamples")}
          </div>
        ) : null}
      </div>
      {confirm ? (
        <ConfirmDialog
          title={t("mfg.sampleLoader.tpl.replaceYourDataWith", { name: confirm.name })}
          confirmLabel={t("mfg.sampleLoader.btn.deleteMyDataAndLoad")}
          danger
          busy={busy !== null}
          onCancel={() => setConfirm(null)}
          onConfirm={() => void run(confirm, true)}
        >
          <p style={{ margin: 0 }}>
            {t("mfg.sampleLoader.text.allYourManufacturingDataItems")}
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
