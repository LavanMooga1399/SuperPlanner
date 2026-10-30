"""Health-check codes (M1-DESIGN 7.2): severity, plain-language message templates and fixes. Codes are stable;
wording may improve. 49 health codes (M2 adds 44-47, M3 adds 48-49) (the 40 of 7.2 plus `MFG_ASSIGNMENT_UNKNOWN_SHIFT`, `MFG_OPERATOR_UNKNOWN_SHIFT`
and `MFG_SERIAL_NOT_ALLOWED`, added by the M1 fix round); the release-only code `MFG_BOM_EMPTY` is listed last."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CodeInfo:
    code: str
    severity: str
    entity: str
    message: str        # str.format template
    fix: str


_C = CodeInfo
CODES: tuple[CodeInfo, ...] = (
    _C("MFG_BOM_CYCLE", "error", "item", "These items contain themselves through their BOMs: {path}.",
       "Remove one of these BOM lines so no item contains itself."),
    _C("MFG_BOM_TOO_DEEP", "error", "item", "The structure of {pn} is deeper than {limit} levels ({depth}).",
       "Check the structure for unintended nesting."),
    _C("MFG_MAKE_NO_ROUTING", "error", "item",
       "Make item {pn} \"{desc}\" has no released routing effective on {day}{draft}.",
       "{fix_draft}"),
    _C("MFG_ROUTING_NO_OPERATIONS", "error", "routing", "Released routing {doc} of {pn} has no operations.",
       "Add operations, or make it obsolete."),
    _C("MFG_GROUP_NO_LINE", "error", "operation", "Operation {op} of {pn} runs on stage {group}, which has no active "
       "line.", "Add a line to the stage or activate one."),
    _C("MFG_NO_ELIGIBLE_LINE", "error", "operation", "No active line of stage {group} may run {pn} (operation {op}).",
       "Add the item or its family to a line's eligibility, or clear the lists."),
    _C("MFG_GROUP_NO_SHIFT", "error", "group", "Stage {group} is used by released routings but has no shift time "
       "between {d0} and {d1}.", "Assign a shift template to the stage or its lines."),
    _C("MFG_GROUP_OPTIONAL_ONLY", "warning", "group", "Stage {group} has only optional (overtime) shift time between "
       "{d0} and {d1}.", "Add a base shift; optional shifts are only opened when needed."),
    _C("MFG_UNINTERRUPTIBLE_TOO_LONG", "error", "operation", "Operation {op} of {pn} must run without interruption "
       "and needs {need} minutes for one unit, but no eligible line of stage {group} has a continuous window that "
       "long (longest {longest} minutes).",
       "Run it on a line with a longer shift (e.g. 24 h), shorten it, or allow interruption."),
    _C("MFG_UNINTERRUPTIBLE_LOT_TOO_LONG", "warning", "operation", "Operation {op} of {pn} must run without "
       "interruption and needs {need} minutes for a lot of {qty}, longer than any continuous window of stage "
       "{group} (longest {longest} minutes).", "Lots this size will need splitting or a longer window."),
    _C("MFG_BUY_NO_LEAD_TIME", "error", "item", "Buy item {pn} \"{desc}\" has no lead time.",
       "Enter the supplier lead time (0 if stocked locally)."),
    _C("MFG_UOM_MISMATCH", "error", "bom_line", "BOM {doc} of {pn}, find {fn}: unit {uom} does not fit {child}, "
       "which is kept in {child_uom}.", "Use a unit of the same kind as the item's unit (EA, or M/CM/MM ...)."),
    _C("MFG_FRACTIONAL_SERIALIZED", "error", "bom_line", "BOM {doc} of {pn}, find {fn}: serialized part {child} is "
       "used {qty} times per unit.", "Serialized parts must be used in whole numbers."),
    _C("MFG_BOM_EFFECTIVITY_OVERLAP", "error", "bom", "BOMs {doc} and {other} of {pn} are both effective at the "
       "same time.", "Set an end date on the older BOM or release the new one with \"supersede\"."),
    _C("MFG_ROUTING_EFFECTIVITY_OVERLAP", "error", "routing", "Routings {doc} and {other} of {pn} (priority "
       "{prio}) are both effective at the same time.",
       "Set an end date on the older routing, release the new one with \"supersede\", or give the alternate a "
       "different priority."),
    _C("MFG_ALT_NO_PRIMARY", "error", "bom_line", "BOM {doc} of {pn}: alternate group {grp} has no priority-1 line.",
       "Mark one alternative as priority 1."),
    _C("MFG_ALT_DUPLICATE_PRIORITY", "error", "bom_line", "BOM {doc} of {pn}: alternate group {grp} has two lines "
       "with priority {prio}.", "Give each alternative its own priority."),
    _C("MFG_INACTIVE_COMPONENT", "error", "bom_line", "BOM {doc} of {pn}, find {fn}: component {child} is inactive.",
       "Activate the item, replace it, or release a new BOM version."),
    _C("MFG_PHANTOM_NO_BOM", "error", "item", "Phantom item {pn} has no released BOM effective on {day}.",
       "Add and release a BOM, or change the item to make/buy."),
    _C("MFG_SKILL_NO_OPERATOR", "error", "operation", "Operation {op} of {pn} needs skill {skill}, which no active "
       "operator has.", "Add the skill to an operator."),
    _C("MFG_TOOL_SHORT", "error", "operation", "Operation {op} of {pn} needs {need} of tool {tool}, but only "
       "{have} exist.", "Increase the tool quantity or reduce the need."),
    _C("MFG_ASSIGNMENT_UNKNOWN_SHIFT", "error", "shift_assignment", "Shift assignment {tpl} on {target} names "
       "{names}, which template {tpl} does not have, so that time is never planned.",
       "Pick shifts of the template in the assignment, or add the shifts back to the template."),
    _C("MFG_OPERATOR_UNKNOWN_SHIFT", "error", "operator", "Operator {op} works {names}, which template {tpl} does "
       "not have, so the operator is never on shift then.",
       "Pick shifts of the template for the operator, or add the shifts back to the template."),
    _C("MFG_SERIAL_NOT_ALLOWED", "error", "item", "{pn} is not serialized, so {what} {doc} cannot have a serial "
       "range.", "Remove the serial range or mark the item as serialized."),
    _C("MFG_ASSIGNMENT_INACTIVE_TARGET", "warning", "shift_assignment", "Shift assignment {tpl} on {target} has no "
       "effect because the {ttype} is inactive.", "Delete the assignment or activate the target."),
    _C("MFG_OPERATION_SEQ_REF", "warning", "bom_line", "BOM {doc} of {pn}, find {fn}: operation {seq} does not exist "
       "in the primary routing (the first operation is used).", "Pick an existing operation number."),
    _C("MFG_SKILL_NOT_ON_SHIFT", "warning", "skill", "No operator with skill {skill} is on shift for line {line} "
       "during {patterns}.", "Put a qualified operator on that shift (or on a template covering it, e.g. an "
       "extended-hours template for overtime crews)."),
    _C("MFG_LINE_NO_SHIFT", "warning", "line", "Line {line} of stage {group} has no shift time between {d0} and "
       "{d1}.", "Assign a shift to the line or its stage."),
    _C("MFG_OPTIONAL_NO_COST", "warning", "shift_assignment", "Optional shift assignment {tpl} on {target} has no "
       "cost per hour.", "Enter the overtime cost so the planner can weigh it."),
    _C("MFG_OPTIONAL_OVERLAPS_BASE", "warning", "shift_assignment", "Optional shift assignment {tpl} on {target} "
       "lies entirely inside base shift time, so it adds nothing.", "Remove it or change its shifts."),
    _C("MFG_MAKE_NO_BOM", "warning", "item", "Make item {pn} \"{desc}\" has no released BOM effective on {day}.",
       "Add a BOM if the item consumes materials."),
    _C("MFG_BOM_EFFECTIVITY_GAP", "warning", "item", "The BOMs of {pn} leave a gap from {g0} to {g1}.",
       "Extend the earlier BOM or start the later one earlier."),
    _C("MFG_ROUTING_EFFECTIVITY_GAP", "warning", "item", "The primary routings of {pn} leave a gap from {g0} to {g1}.",
       "Extend the earlier routing or start the later one earlier."),
    _C("MFG_BUY_WITH_BOM", "warning", "item", "Buy item {pn} has a BOM ({doc}); it is ignored.",
       "Change it to make, or make the BOM obsolete."),
    _C("MFG_BUY_WITH_ROUTING", "warning", "item", "{mb} item {pn} has a routing ({doc}); it is ignored.",
       "Change the item to make, or make the routing obsolete."),
    _C("MFG_ALT_SINGLE", "warning", "bom_line", "BOM {doc} of {pn}: alternate group {grp} has only one line.",
       "Add the alternative or clear the group."),
    _C("MFG_REFDES_COUNT", "warning", "bom_line", "BOM {doc} of {pn}, find {fn}: {count} reference designators for "
       "quantity {qty}{invalid}.", "Correct the quantity or the reference designators."),
    _C("MFG_ZERO_TIME_OPERATION", "warning", "operation", "Operation {op} of {pn} has no setup and no run time.",
       "Enter setup/run times."),
    _C("MFG_LOW_YIELD", "warning", "routing", "Routing {doc} of {pn} has a cumulative yield of {pct}%.",
       "Check yield percentages."),
    _C("MFG_ORPHAN_ITEM", "warning", "item", "Item {pn} \"{desc}\" is not used in any BOM and is not an end item.",
       "Use it in a BOM or deactivate it."),
    _C("MFG_DUPLICATE_COMPONENT", "info", "bom_line", "BOM {doc} of {pn} uses {child} at find numbers {fns}.",
       "Fine if intended (different positions)."),
    _C("MFG_LONG_LEAD_TIME", "info", "item", "Buy item {pn} \"{desc}\" has a lead time of {days} days.",
       "Long-lead part: order early (M2 will flag it)."),
    _C("MFG_DRAFT_ONLY", "info", "item", "Item {pn} has only draft {what}.", "Release when ready."),
    # M2-DESIGN 3.11 (44-47)
    _C("MFG_BUY_NO_SUPPLIER", "info", "item", "Buy item {pn} \"{desc}\" has no active supplier, so MRP uses the item "
       "lead time and plans purchase requests without a supplier.", "Add a supplier for this part."),
    _C("MFG_PREFERRED_SUPPLIER_INACTIVE", "warning", "item_supplier", "The preferred supplier {sup} of {pn} is "
       "inactive.", "Choose another preferred supplier or activate this one."),
    _C("MFG_NO_NETTABLE_LOCATION", "warning", "plant", "No active stores or line-side location exists, so no stock "
       "can be planned or kitted.", "Add a stores location."),
    _C("MFG_PACK_FRACTIONAL", "warning", "item_supplier", "{pn} is counted in {uom} but supplier {sup} packs "
       "{pack} units per {unit}.", "Use a whole number of units per pack."),
    # M3-DESIGN 3.2 (48-49)
    _C("MFG_RATE_LINE_INELIGIBLE", "warning", "operation_line_rate", "A line rate of {pn} operation {seq} is for line "
       "{line}, which is not eligible for {pn}.", "Delete the rate or make the line eligible for the item."),
    _C("MFG_TZ_NOT_SET", "info", "plant", "The plant has no time zone, so schedules use the fixed offset {off} "
       "(no daylight-saving changes).", "Set the plant time zone (for example Asia/Kolkata)."),
    # release-only codes (4.2)
    _C("MFG_BOM_EMPTY", "error", "bom", "BOM {doc} of {pn} has no lines.", "Add lines before releasing."),
)
RELEASE_ONLY_CODES: tuple[str, ...] = ("MFG_BOM_EMPTY",)
HEALTH_CODES: tuple[str, ...] = tuple(c.code for c in CODES if c.code not in RELEASE_ONLY_CODES)
CODE_INFO: dict[str, CodeInfo] = {c.code: c for c in CODES}
CODE_ORDER: dict[str, int] = {c.code: i for i, c in enumerate(CODES)}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def message(code: str, **kw: object) -> str:
    return CODE_INFO[code].message.format(**kw)


def fix(code: str, **kw: object) -> str:
    return CODE_INFO[code].fix.format(**kw)
