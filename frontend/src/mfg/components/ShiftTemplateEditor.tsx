/**
 * Shift template editor (M 11.2): shifts with day toggles, start/end (HH:MM; end at or before start = ends
 * the next day; "24:00" = midnight) and breaks. Guided starting patterns for new templates.
 */
import { Icon } from "../../components/Icon";
import { WEEKDAYS, type ShiftDef, type Weekday } from "../api/types";
import { WEEKDAY_LABEL } from "../lib/format";
import { t } from "../../lib/i18n";

const MON_FRI: Weekday[] = ["mon", "tue", "wed", "thu", "fri"];
const MON_SAT: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat"];

export const SHIFT_PATTERNS: { id: string; label: string; shifts: ShiftDef[] }[] = [
  { id: "day", label: t("mfg.shiftTemplateEditor.str.dayShiftMonFri08"), shifts: [{ name: t("mfg.shiftTemplateEditor.str.day"), days: MON_FRI, start: "08:00", end: "17:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.lunch"), start: "12:00", end: "13:00" }] }] },
  {
    id: "two",
    label: t("mfg.shiftTemplateEditor.str.twoShiftsMonFri06"),
    shifts: [
      { name: t("mfg.shiftTemplateEditor.str.early"), days: MON_FRI, start: "06:00", end: "14:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.meal"), start: "10:00", end: "10:30" }] },
      { name: t("mfg.shiftTemplateEditor.str.late"), days: MON_FRI, start: "14:00", end: "22:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.meal"), start: "18:00", end: "18:30" }] },
    ],
  },
  {
    id: "three",
    label: t("mfg.shiftTemplateEditor.str.threeShifts24HMon"),
    shifts: [
      { name: "A", days: MON_SAT, start: "06:00", end: "14:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.meal"), start: "10:00", end: "10:30" }] },
      { name: "B", days: MON_SAT, start: "14:00", end: "22:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.meal"), start: "18:00", end: "18:30" }] },
      { name: "C", days: MON_SAT, start: "22:00", end: "06:00", breaks: [{ name: t("mfg.shiftTemplateEditor.str.meal"), start: "02:00", end: "02:30" }] },
    ],
  },
  { id: "24x7", label: t("mfg.shiftTemplateEditor.str.roundTheClockEveryDay"), shifts: [{ name: "24h", days: [...WEEKDAYS], start: "00:00", end: "00:00", breaks: [] }] },
];

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$|^24:00$/;

export function shiftProblems(s: ShiftDef): string[] {
  const p: string[] = [];
  if (!s.name.trim()) p.push(t("mfg.shiftTemplateEditor.str.nameTheShift"));
  if (s.days.length === 0) p.push(t("mfg.shiftTemplateEditor.str.pickAtLeastOneDay"));
  if (!HHMM.test(s.start) || s.start === "24:00") p.push(t("mfg.shiftTemplateEditor.str.startMustBeHhMm"));
  if (!HHMM.test(s.end)) p.push(t("mfg.shiftTemplateEditor.str.endMustBeHhMm"));
  for (const b of s.breaks) if (!HHMM.test(b.start) || !HHMM.test(b.end)) p.push(t("mfg.shiftTemplateEditor.str.breaksNeedHhMmTimes"));
  return p;
}

function endHint(s: ShiftDef): string {
  if (!HHMM.test(s.start) || !HHMM.test(s.end)) return "";
  if (s.start === s.end) return "24 hours";
  if (s.end === "24:00") return t("mfg.shiftTemplateEditor.str.endsAtMidnight");
  if (s.end < s.start) return t("mfg.shiftTemplateEditor.str.endsTheNextMorning");
  return "";
}

export function ShiftTemplateEditor({ shifts, onChange, readOnly }: { shifts: ShiftDef[]; onChange(next: ShiftDef[]): void; readOnly?: boolean }) {
  const update = (i: number, patch: Partial<ShiftDef>) => onChange(shifts.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const toggleDay = (i: number, d: Weekday) => {
    const days = shifts[i].days.includes(d) ? shifts[i].days.filter((x) => x !== d) : WEEKDAYS.filter((x) => x === d || shifts[i].days.includes(x));
    update(i, { days });
  };
  return (
    <div className="col" data-testid="shift-template-shifts">
      {shifts.map((s, i) => {
        const probs = shiftProblems(s);
        const hint = endHint(s);
        return (
          <fieldset key={i} className="mfg-fieldset" data-testid="shift-def">
            <legend>{t("mfg.shiftTemplateEditor.text.shift", { v: i + 1 })}</legend>
            <div className="row wrap" style={{ alignItems: "flex-end" }}>
              <div className="field" style={{ width: 120 }}>
                <label htmlFor={`sh-${i}-name`}>{t("mfg.shiftTemplateEditor.text.name")}</label>
                <input id={`sh-${i}-name`} className="input sm" value={s.name} maxLength={32} readOnly={readOnly} onChange={(e) => update(i, { name: e.target.value })} data-testid="shift-name" />
              </div>
              <div className="field" style={{ width: 86 }}>
                <label htmlFor={`sh-${i}-start`}>{t("mfg.shiftTemplateEditor.text.start")}</label>
                <input id={`sh-${i}-start`} className="input sm mono" value={s.start} placeholder={t("mfg.shiftTemplateEditor.ph.hhmm")} maxLength={5} readOnly={readOnly} aria-invalid={!HHMM.test(s.start)} onChange={(e) => update(i, { start: e.target.value })} data-testid="shift-start" />
              </div>
              <div className="field" style={{ width: 86 }}>
                <label htmlFor={`sh-${i}-end`}>End</label>
                <input id={`sh-${i}-end`} className="input sm mono" value={s.end} placeholder={t("mfg.shiftTemplateEditor.ph.hhmm")} maxLength={5} readOnly={readOnly} aria-invalid={!HHMM.test(s.end)} onChange={(e) => update(i, { end: e.target.value })} data-testid="shift-end" />
              </div>
              {hint ? <span className="small muted" style={{ paddingBottom: 6 }}>{hint}</span> : null}
              <div className="field">
                <span className="field-label" id={`sh-${i}-days`}>
                  {t("mfg.shiftTemplateEditor.text.startsOn")}
                </span>
                <div className="btn-group" role="group" aria-labelledby={`sh-${i}-days`}>
                  {WEEKDAYS.map((d) => (
                    <button key={d} type="button" className="btn sm" aria-pressed={s.days.includes(d)} disabled={readOnly} onClick={() => toggleDay(i, d)} data-testid={`shift-day-${d}`}>
                      {WEEKDAY_LABEL[d]}
                    </button>
                  ))}
                </div>
              </div>
              <span className="grow" />
              {readOnly ? null : (
                <button type="button" className="btn sm ghost icon" aria-label={t("mfg.shiftTemplateEditor.tpl.removeShift", { v: i + 1 })} onClick={() => onChange(shifts.filter((_, j) => j !== i))} data-testid="shift-remove">
                  <Icon name="trash" />
                </button>
              )}
            </div>
            <div className="col" style={{ gap: 4 }}>
              {s.breaks.map((b, j) => (
                <div className="row" key={j}>
                  <span className="small muted" style={{ width: 48 }}>
                    {t("mfg.shiftTemplateEditor.text.break")}
                  </span>
                  <input className="input sm" style={{ width: 110 }} aria-label={t("mfg.shiftTemplateEditor.tpl.breakNameShift", { v: j + 1, v2: i + 1 })} value={b.name} maxLength={32} readOnly={readOnly} onChange={(e) => update(i, { breaks: s.breaks.map((x, n) => (n === j ? { ...x, name: e.target.value } : x)) })} />
                  <input className="input sm mono" style={{ width: 76 }} placeholder={t("mfg.shiftTemplateEditor.ph.hhmm")} aria-label={t("mfg.shiftTemplateEditor.tpl.breakStartShift", { v: j + 1, v2: i + 1 })} value={b.start} maxLength={5} readOnly={readOnly} onChange={(e) => update(i, { breaks: s.breaks.map((x, n) => (n === j ? { ...x, start: e.target.value } : x)) })} />
                  <span aria-hidden>-</span>
                  <input className="input sm mono" style={{ width: 76 }} placeholder={t("mfg.shiftTemplateEditor.ph.hhmm")} aria-label={t("mfg.shiftTemplateEditor.tpl.breakEndShift", { v: j + 1, v2: i + 1 })} value={b.end} maxLength={5} readOnly={readOnly} onChange={(e) => update(i, { breaks: s.breaks.map((x, n) => (n === j ? { ...x, end: e.target.value } : x)) })} />
                  {readOnly ? null : (
                    <button type="button" className="btn sm ghost icon" aria-label={t("mfg.shiftTemplateEditor.tpl.removeBreakShift", { v: j + 1, v2: i + 1 })} onClick={() => update(i, { breaks: s.breaks.filter((_, n) => n !== j) })}>
                      <Icon name="x" />
                    </button>
                  )}
                </div>
              ))}
              {readOnly ? null : (
                <div>
                  <button type="button" className="btn sm ghost" onClick={() => update(i, { breaks: [...s.breaks, { name: "Break", start: "", end: "" }] })} data-testid="shift-add-break">
                    <Icon name="plus" /> {t("mfg.shiftTemplateEditor.btn.addBreak")}
                  </button>
                </div>
              )}
            </div>
            {probs.length ? (
              <span className="field-error" role="status">
                <Icon name="alert" size={12} /> {probs.join("; ")}
              </span>
            ) : null}
          </fieldset>
        );
      })}
      {readOnly ? null : (
        <div>
          <button
            type="button"
            className="btn sm"
            onClick={() => onChange([...shifts, { name: `Shift ${shifts.length + 1}`, days: [...MON_FRI], start: "08:00", end: "16:00", breaks: [] }])}
            data-testid="shift-add"
            disabled={shifts.length >= 10}
          >
            <Icon name="plus" /> {t("mfg.shiftTemplateEditor.btn.addShift")}
          </button>
        </div>
      )}
    </div>
  );
}
