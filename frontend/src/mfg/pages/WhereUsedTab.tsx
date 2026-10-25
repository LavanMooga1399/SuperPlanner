/** `/mfg/items/:itemId/where-used` (M 11.1): direct parents or the full chain up, effective or all versions. */
import { useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { Banner } from "../../components/Banner";
import { getWhereUsed } from "../api/client";
import type { WhereUsedInclude, WhereUsedMode, WhereUsedRow } from "../api/types";
import { MfgError, Spinner } from "../components/Feedback";
import { StatusChip } from "../components/StatusChip";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { fmtQty } from "../lib/format";
import { mfgPaths } from "../lib/paths";
import { errorText, useLoad } from "../lib/useMfg";
import { useItem } from "./ItemShell";

export function WhereUsedTab() {
  const { item } = useItem();
  const [mode, setMode] = useState<WhereUsedMode>("single");
  const [include, setInclude] = useState<WhereUsedInclude>("effective");
  const [on, setOn] = useState("");
  const wu = useLoad((signal) => getWhereUsed(item.id, { mode, include, on: on || undefined }, signal), [item.id, mode, include, on]);
  const tooLarge = wu.error instanceof ApiError && wu.error.code === "MFG_EXPLOSION_TOO_LARGE";

  const columns: Column<WhereUsedRow>[] = [
    {
      key: "pn",
      header: "Used in",
      width: "minmax(220px, 1.3fr)",
      render: (r) => (
        <span style={{ paddingLeft: (r.level - 1) * 18 }} className="row">
          <Link to={mfgPaths.itemBom(r.item_id, { bom: r.bom_id, line: r.line_id })} className="mono" tabIndex={-1}>
            {r.part_number}
          </Link>
          {r.is_top ? (
            <span className="chip" title="Not used anywhere else: a finished product">
              Top
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(180px, 1.5fr)", render: (r) => <span className="mfg-ellipsis">{r.description}</span> },
    { key: "lvl", header: "Level", width: "60px", align: "right", render: (r) => r.level },
    {
      key: "bom",
      header: "BOM",
      width: "180px",
      render: (r) => (
        <span className="row" style={{ gap: 4 }}>
          rev. {r.bom_revision} v{r.bom_version} <StatusChip status={r.bom_status} />
        </span>
      ),
    },
    { key: "fn", header: "Find no.", width: "70px", render: (r) => <span className="mono">{r.find_number}</span> },
    { key: "qty", header: "Qty per", width: "90px", align: "right", render: (r) => `${fmtQty(r.qty_per)} ${r.line_uom}` },
  ];

  return (
    <div className="col">
      <div className="toolbar">
        <div className="btn-group" role="group" aria-label="Depth">
          <button type="button" className="btn sm" aria-pressed={mode === "single"} onClick={() => setMode("single")} data-testid="whereused-mode-single">
            Direct parents
          </button>
          <button type="button" className="btn sm" aria-pressed={mode === "indented"} onClick={() => setMode("indented")} data-testid="whereused-mode-indented">
            All levels up
          </button>
        </div>
        <div className="btn-group" role="group" aria-label="Versions">
          <button type="button" className="btn sm" aria-pressed={include === "effective"} onClick={() => setInclude("effective")} data-testid="whereused-include-effective">
            Released and effective
          </button>
          <button type="button" className="btn sm" aria-pressed={include === "all"} onClick={() => setInclude("all")} data-testid="whereused-include-all">
            All versions (incl. drafts)
          </button>
        </div>
        <label className="row small">
          <span className="muted">On date</span>
          <input type="date" className="input sm" value={on} onChange={(e) => setOn(e.target.value)} aria-label="On date (empty = any date)" />
        </label>
      </div>
      {tooLarge ? (
        <Banner tone="warn" title="Too many rows to show all levels" actions={<button type="button" className="btn sm" onClick={() => setMode("single")}>Show direct parents</button>}>
          {errorText(wu.error)}
        </Banner>
      ) : (
        <MfgError error={wu.error} onRetry={wu.reload} />
      )}
      {wu.loading && !wu.data ? <Spinner /> : null}
      {wu.data ? (
        <VirtualTable
          rows={wu.data.rows}
          columns={columns}
          rowKey={(r) => `${r.row}-${r.line_id}`}
          label={`Where ${item.part_number} is used`}
          role={mode === "indented" ? "treegrid" : "grid"}
          testId="whereused-table"
          rowExtras={(r) => ({ testId: "whereused-row", data: { "part-number": r.part_number, level: r.level }, ariaLevel: mode === "indented" ? r.level : undefined })}
          empty={`${item.part_number} is not used in any ${include === "effective" ? "effective released" : ""} BOM.`}
          footer={
            <span className="small muted">
              {wu.data.totals.rows} rows · {wu.data.totals.top_items} top-level products
            </span>
          }
        />
      ) : null}
    </div>
  );
}
