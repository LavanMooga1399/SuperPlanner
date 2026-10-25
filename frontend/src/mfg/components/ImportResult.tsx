/** Step 4 Done (M 11.5): result counts and where to go next. */
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import type { ImportRecord } from "../api/types";
import { fmtTimestamp } from "../lib/format";
import { mfgPaths } from "../lib/paths";
import { sheetLabel } from "./ImportUpload";

export function ImportResult({ record }: { record: ImportRecord }) {
  const r = record.result;
  const rows = Object.entries(r?.counts ?? {});
  return (
    <div className="col gap-lg" data-testid="import-result">
      <Banner tone="ok" title={`Imported ${record.filename}`}>
        Saved {record.committed_at ? fmtTimestamp(record.committed_at) : ""}
        {r ? ` in ${(r.duration_ms / 1000).toFixed(1)} s` : ""}. Run the data-health check to see whether everything is ready for planning.
      </Banner>
      {rows.length ? (
        <div className="table-wrap">
          <table className="table" data-testid="import-result-counts">
            <thead>
              <tr>
                <th>Data</th>
                <th className="num">New</th>
                <th className="num">Changed</th>
                <th className="num">Same</th>
                <th className="num">Removed</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([name, c]) => (
                <tr key={name} data-sheet={name}>
                  <td>{sheetLabel(name)}</td>
                  <td className="num">{c.create ?? 0}</td>
                  <td className="num">{c.update ?? 0}</td>
                  <td className="num">{c.unchanged ?? 0}</td>
                  <td className="num">{c.delete ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="row wrap">
        <Link className="btn primary" to={mfgPaths.health()} data-testid="import-done-health">
          <Icon name="check" /> Check data health
        </Link>
        <Link className="btn" to={mfgPaths.items()}>
          Browse items
        </Link>
        <Link className="btn ghost" to={mfgPaths.importStart()}>
          Import another file
        </Link>
      </div>
    </div>
  );
}
