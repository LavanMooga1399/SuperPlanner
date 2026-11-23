import type { Violation } from "../api/types";
import { Icon } from "./Icon";
import { t } from "../lib/i18n";

export function ViolationsPanel({
  violations,
  open,
  onToggle,
  onSelectTask,
}: {
  violations: Violation[];
  open: boolean;
  onToggle(): void;
  onSelectTask(id: string): void;
}) {
  const hard = violations.filter((v) => v.severity === "hard");
  const soft = violations.filter((v) => v.severity === "soft");
  if (!violations.length) return null;
  return (
    <div className="card" data-testid="violations-panel">
      <div className="card-header">
        <button type="button" className="btn ghost sm" aria-expanded={open} onClick={onToggle}>
          <Icon name={open ? "chevron-down" : "chevron-right"} />
          <strong>
            {hard.length ? t("studio.violationsPanel.tpl.ruleViolation", { length: hard.length, v: hard.length === 1 ? "" : "s" }) : ""}
            {hard.length && soft.length ? " and " : ""}
            {soft.length ? t("studio.violationsPanel.tpl.missedTarget", { length: soft.length, v: soft.length === 1 ? "" : "s" }) : ""}
          </strong>
        </button>
        {hard.length ? (
          <span className="badge danger"><Icon name="x" />{" "}{t("studio.violationsPanel.text.cannotBeApproved")}</span>
        ) : (
          <span className="badge warn"><Icon name="alert" />{" "}{t("studio.violationsPanel.text.softOnly")}</span>
        )}
      </div>
      {open ? (
        <div>
          {[...hard, ...soft].map((v, i) => (
            <div className="issue" key={i} data-testid={`violation-${v.code}`}>
              <span className={`badge ${v.severity === "hard" ? "danger" : "warn"}`}>
                <Icon name={v.severity === "hard" ? "x" : "clock"} />
                {v.severity === "hard" ? t("studio.violationsPanel.str.ruleBroken") : t("studio.violationsPanel.str.late")}
              </span>
              <div className="grow">
                <div>{v.message}</div>
                <div className="small faint"><code>{v.code}</code></div>
              </div>
              {v.task_ids.length ? (
                <button className="btn sm" onClick={() => onSelectTask(v.task_ids[0])}>
                  {t("studio.violationsPanel.btn.show")}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
