"""M10 `/api/v1/mfg` endpoints (M10-DESIGN 10: D1-D10, V1-V4, C1-C9, U1-U5, L1-L13, Q1-Q5; one permission
each). Services: `services/{dhr,deviations,coa,labels,udi,valpkg}.py`; until a service function is implemented it
answers from `api/mfg/fixtures/example_m10.json` (`services/m10_examples.py`, PEP 562 fallback as M8/M9).

Fixed paths precede parameterised siblings; path ids are plain `str` (malformed / unknown / foreign -> 404).
Signed actions (`/release`, `/approve`) need only `view`: who may sign is decided by the signature policy
(`dhr.release`, `deviation.approve`, `customer_agreement.approve`, `coa.approve`, `udi_device.approve`,
`validation_package.approve`). Binary downloads answer with their media type and `Content-Disposition`;
the response header `X-Content-SHA256` carries the sha256 of the bytes.

Route table (S0 contract; response shapes in `example_m10.json`, keys in brackets):

    GET  /dhr                                   view          list [dhr_summary]
    GET  /dhr/review-queue                      view          items [review_queue_row]
    GET  /dhr/live?lot_id|wo_id                 view          one [dhr_record] (id "live", status "open")
    POST /dhr                                   dhr_review    one [dhr_record] (201)
    GET  /dhr/{dhr_id}                          view          one [dhr_record]
    GET  /dhr/{dhr_id}/sections/{section}       view          one [dhr_section]
    PUT  /dhr/{dhr_id}/exceptions/{exception_id} dhr_review   one [dhr_exception] (If-Match)
    POST /dhr/{dhr_id}/start-review             dhr_review    one [dhr_record]
    POST /dhr/{dhr_id}/release                  view (signed) one [dhr_record] | 202 pending_signatures
    GET  /dhr/{dhr_id}/export?format=pdf|json   view          file
    GET  /deviations                            view          list [deviation]
    POST /deviations                            deviation_edit one [deviation] (201)
    GET  /deviations/{deviation_id}             view          one [deviation]
    PUT  /deviations/{deviation_id}             deviation_edit one [deviation] (If-Match, draft only)
    POST /deviations/{deviation_id}/approve     view (signed) one [deviation] | 202
    POST /deviations/{deviation_id}/close       deviation_edit one [deviation] (If-Match)
    GET  /qa/agreements                         view          list [agreement]
    POST /qa/agreements                         coa_edit      one [agreement] (201)
    GET  /qa/agreements/{agreement_id}          view          one [agreement]
    PUT  /qa/agreements/{agreement_id}          coa_edit      one [agreement] (If-Match, draft only)
    POST /qa/agreements/{agreement_id}/approve  view (signed) one [agreement] | 202
    POST /qa/agreements/{agreement_id}/new-version coa_edit   one [agreement] (201)
    GET  /coa?lot_id                            view          list [coa]
    POST /coa                                   coa_edit      one [coa] (201)
    GET  /coa/{coa_id}                          view          one [coa]
    POST /coa/{coa_id}/approve                  view (signed) one [coa] | 202
    POST /coa/{coa_id}/void                     coa_edit      one [coa] (If-Match)
    GET  /coa/{coa_id}/export?format=pdf|json   view          file
    GET  /batch-packs?lot_id                    view          list [batch_pack]
    POST /batch-packs                           coa_edit      one [batch_pack] (202)
    GET  /batch-packs/{pack_id}                 view          one [batch_pack]
    GET  /batch-packs/{pack_id}/download        view          file (zip)
    GET  /udi/devices?item_id                   view          items [udi_device]
    PUT  /udi/devices                           udi_edit      one [udi_device] (If-Match on update)
    GET  /udi/parse?code=                       view          one [udi_parse]
    POST /udi/devices/{udi_id}/approve          view (signed) one [udi_device] | 202
    GET  /udi/exports                           udi_export    list [udi_export]
    POST /udi/exports                           udi_export    one [udi_export] (202)
    GET  /udi/exports/{udi_export_id}           udi_export    one [udi_export]
    GET  /udi/exports/{udi_export_id}/download  udi_export    file (csv | xlsx | json)
    GET  /labels/templates                      view          list [label_template]
    POST /labels/templates                      label_admin   one [label_template] (201)
    GET  /labels/templates/{label_template_id}  view          one [label_template]
    PUT  /labels/templates/{label_template_id}  label_admin   one [label_template] (If-Match, draft only)
    POST /labels/templates/{label_template_id}/new-version label_admin one [label_template] (201)
    GET  /labels/templates/{label_template_id}/preview.svg?item_id&lot_id  view  image/svg+xml
    GET  /labels/assignments                    view          items [label_assignment]
    PUT  /labels/assignments                    label_admin   items [label_assignment]
    GET  /labels/printers                       view          items [printer]
    POST /labels/printers                       label_admin   one [printer] (201)
    PUT  /labels/printers/{printer_id}          label_admin   one [printer] (If-Match)
    GET  /labels/jobs?lot_id&status             view          list [print_job]
    POST /labels/jobs                           label_print   one [print_job] (201)
    GET  /labels/jobs/{print_job_id}            view          one [print_job]
    GET  /labels/jobs/{print_job_id}/output?reprint_reason&qty  label_print  file (zpl | pdf)
    POST /labels/jobs/{print_job_id}/events     label_print   one [print_job]
    POST /labels/jobs/{print_job_id}/verify     label_print   one [verify_result]
    POST /labels/jobs/{print_job_id}/reconcile  label_print   one [print_job] | 202 (signed when required)
    POST /labels/jobs/{print_job_id}/void       label_print   one [print_job]
    POST /validation/iq-check                   validation_admin  one [iq_result]
    GET  /validation/packages                   validation_view   list [val_package]
    POST /validation/packages                   validation_admin  one [val_package] (202)
    GET  /validation/packages/{package_id}      validation_view   one [val_package]
    GET  /validation/packages/{package_id}/download  validation_view  file (zip)
    POST /validation/packages/{package_id}/approve   view (signed)    one [val_package] | 202
    POST /validation/evidence                   validation_admin  one [val_package] (201; kind evidence)
    GET  /orgs/{org_id}/residency               (orgs router, org_admin)              one [residency]
    GET  /orgs/{org_id}/audit                   (orgs router, org_admin | org_auditor) list [org_audit_row]
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from ...dhr.model import DhrAssembleInput, DhrReleaseInput, DispositionInput, StartReviewInput
from ...qa.model_m10 import (AgreementInput, BatchPackInput, CoaInput, DeviationApproveInput, DeviationCloseInput,
                             DeviationInput, SignInput, VoidInput)
from ...udi.model import (ApproveInput, AssignmentsInput, LabelTemplateInput, PrintEventInput, PrinterInput,
                          PrintJobInput, ReconcileInput, UdiDeviceInput, UdiExportInput, VerifyInput)
from ...udi.model import VoidInput as JobVoidInput
from ...validation.model import ApproveInput as PkgApproveInput
from ...validation.model import PackageInput
from ..context import AppContext, get_ctx
from .router_m2 import P, Id, Limit, Offset, _if_match, _ok
from .services.qa_common import Act, act

router = APIRouter(prefix="/mfg", tags=["mfg-m10"])
Status = Query(default=None, max_length=64)


def _rec(result: Any, status: int = 200) -> JSONResponse:
    etag = result.get("row_version") if isinstance(result, dict) else None
    return _ok(result, status, etag=etag if isinstance(etag, int) else None)


def _signed(result: Any) -> JSONResponse:
    if isinstance(result, dict) and result.get("status") == "pending_signatures":
        return _ok(result, 202)
    return _rec(result)


def _file(out: Any) -> Response:
    """(bytes, filename, media type) -> a download; a dict (stub / JSON) answers as JSON."""
    if isinstance(out, tuple):
        import hashlib

        data, name, media = out
        return Response(data, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": hashlib.sha256(data).hexdigest()})
    return _ok(out)


# ---------------------------------------------------------------- D1-D10 eDHR

@router.get("/dhr", dependencies=P("view"))
def list_dhr(status: str | None = Status, item_id: str | None = Id(), from_: date | None = Query(default=None,
             alias="from"), to: date | None = None, open_only: bool = False, lot_id: str | None = Id(),
             limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _ok(dhr.list_records(ctx, status, item_id, from_, to, open_only, lot_id, limit, offset))


@router.get("/dhr/review-queue", dependencies=P("view"))
def review_queue(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _ok(dhr.review_queue(ctx))


@router.get("/dhr/live", dependencies=P("view"))
def live_dhr(lot_id: str | None = Id(), wo_id: str | None = Id(), ctx: AppContext = Depends(get_ctx)
             ) -> JSONResponse:
    from .services import dhr

    return _ok(dhr.live(ctx, lot_id, wo_id))


@router.post("/dhr", status_code=201, dependencies=P("dhr_review"))
def assemble_dhr(body: DhrAssembleInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _rec(dhr.assemble(ctx, a, body), 201)


@router.get("/dhr/{dhr_id}", dependencies=P("view"))
def get_dhr(dhr_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _rec(dhr.get_record(ctx, dhr_id))


@router.get("/dhr/{dhr_id}/sections/{section}", dependencies=P("view"))
def dhr_section(dhr_id: str, section: str, page: int = Query(default=1, ge=1, le=100_000), limit: int = Query(
                default=500, ge=1, le=5000), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _ok(dhr.section(ctx, dhr_id, section, page, limit))


@router.put("/dhr/{dhr_id}/exceptions/{exception_id}", dependencies=P("dhr_review"))
def disposition(dhr_id: str, exception_id: str, body: DispositionInput, if_match: str | None = _if_match(),
                a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _rec(dhr.disposition(ctx, a, dhr_id, exception_id, body, if_match))


@router.post("/dhr/{dhr_id}/start-review", dependencies=P("dhr_review"))
def start_review(dhr_id: str, body: StartReviewInput | None = None, a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dhr

    return _rec(dhr.start_review(ctx, a, dhr_id, body or StartReviewInput()))


@router.post("/dhr/{dhr_id}/release", dependencies=P("view"))
def release_dhr(dhr_id: str, body: DhrReleaseInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import dhr

    return _signed(dhr.release(ctx, a, dhr_id, body))


@router.get("/dhr/{dhr_id}/export", dependencies=P("view"))
def export_dhr(dhr_id: str, format: Literal["pdf", "json"] = "pdf", a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import dhr

    return _file(dhr.export(ctx, a, dhr_id, format))


# ---------------------------------------------------------------- V1-V4 deviations

@router.get("/deviations", dependencies=P("view"))
def list_deviations(status: str | None = Status, kind: str | None = Status, item_id: str | None = Id(),
                    lot_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import deviations

    return _ok(deviations.list_deviations(ctx, status, kind, item_id, lot_id, limit, offset))


@router.post("/deviations", status_code=201, dependencies=P("deviation_edit"))
def create_deviation(body: DeviationInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                     ) -> JSONResponse:
    from .services import deviations

    return _rec(deviations.create(ctx, a, body), 201)


@router.get("/deviations/{deviation_id}", dependencies=P("view"))
def get_deviation(deviation_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import deviations

    return _rec(deviations.get(ctx, deviation_id))


@router.put("/deviations/{deviation_id}", dependencies=P("deviation_edit"))
def update_deviation(deviation_id: str, body: DeviationInput, if_match: str | None = _if_match(),
                     a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import deviations

    return _rec(deviations.update(ctx, a, deviation_id, body, if_match))


@router.post("/deviations/{deviation_id}/approve", dependencies=P("view"))
def approve_deviation(deviation_id: str, body: DeviationApproveInput, a: Act = Depends(act),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import deviations

    return _signed(deviations.approve(ctx, a, deviation_id, body))


@router.post("/deviations/{deviation_id}/close", dependencies=P("deviation_edit"))
def close_deviation(deviation_id: str, body: DeviationCloseInput, if_match: str | None = _if_match(),
                    a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import deviations

    return _rec(deviations.close(ctx, a, deviation_id, body, if_match))


# ---------------------------------------------------------------- C1-C3 customer agreements

@router.get("/qa/agreements", dependencies=P("view"))
def list_agreements(customer: str | None = Query(default=None, max_length=100), status: str | None = Status,
                    limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)
                    ) -> JSONResponse:
    from .services import coa

    return _ok(coa.list_agreements(ctx, customer, status, limit, offset))


@router.post("/qa/agreements", status_code=201, dependencies=P("coa_edit"))
def create_agreement(body: AgreementInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                     ) -> JSONResponse:
    from .services import coa

    return _rec(coa.create_agreement(ctx, a, body), 201)


@router.get("/qa/agreements/{agreement_id}", dependencies=P("view"))
def get_agreement(agreement_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.get_agreement(ctx, agreement_id))


@router.put("/qa/agreements/{agreement_id}", dependencies=P("coa_edit"))
def update_agreement(agreement_id: str, body: AgreementInput, if_match: str | None = _if_match(),
                     a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.update_agreement(ctx, a, agreement_id, body, if_match))


@router.post("/qa/agreements/{agreement_id}/approve", dependencies=P("view"))
def approve_agreement(agreement_id: str, body: SignInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                      ) -> JSONResponse:
    from .services import coa

    return _signed(coa.approve_agreement(ctx, a, agreement_id, body))


@router.post("/qa/agreements/{agreement_id}/new-version", status_code=201, dependencies=P("coa_edit"))
def new_agreement_version(agreement_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                          ) -> JSONResponse:
    from .services import coa

    return _rec(coa.new_agreement_version(ctx, a, agreement_id), 201)


# ---------------------------------------------------------------- C4-C9 CoA and batch packs

@router.get("/coa", dependencies=P("view"))
def list_coas(lot_id: str | None = Id(), status: str | None = Status, limit: int = Limit(), offset: int = Offset(),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _ok(coa.list_coas(ctx, lot_id, status, limit, offset))


@router.post("/coa", status_code=201, dependencies=P("coa_edit"))
def create_coa(body: CoaInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.create_coa(ctx, a, body), 201)


@router.get("/coa/{coa_id}", dependencies=P("view"))
def get_coa(coa_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.get_coa(ctx, coa_id))


@router.post("/coa/{coa_id}/approve", dependencies=P("view"))
def approve_coa(coa_id: str, body: SignInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import coa

    return _signed(coa.approve_coa(ctx, a, coa_id, body))


@router.post("/coa/{coa_id}/void", dependencies=P("coa_edit"))
def void_coa(coa_id: str, body: VoidInput, if_match: str | None = _if_match(), a: Act = Depends(act),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.void_coa(ctx, a, coa_id, body, if_match))


@router.get("/coa/{coa_id}/export", dependencies=P("view"))
def export_coa(coa_id: str, format: Literal["pdf", "json"] = "pdf", a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import coa

    return _file(coa.export_coa(ctx, a, coa_id, format))


@router.get("/batch-packs", dependencies=P("view"))
def list_packs(lot_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _ok(coa.list_packs(ctx, lot_id, limit, offset))


@router.post("/batch-packs", status_code=202, dependencies=P("coa_edit"))
def create_pack(body: BatchPackInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _ok(coa.create_pack(ctx, a, body), 202)


@router.get("/batch-packs/{pack_id}", dependencies=P("view"))
def get_pack(pack_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import coa

    return _rec(coa.get_pack(ctx, pack_id))


@router.get("/batch-packs/{pack_id}/download", dependencies=P("view"))
def download_pack(pack_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import coa

    return _file(coa.download_pack(ctx, a, pack_id))


# ---------------------------------------------------------------- U1-U5 UDI

@router.get("/udi/devices", dependencies=P("view"))
def list_devices(item_id: str | None = Id(), status: str | None = Status, ctx: AppContext = Depends(get_ctx)
                 ) -> JSONResponse:
    from .services import udi

    return _ok(udi.list_devices(ctx, item_id, status))


@router.put("/udi/devices", dependencies=P("udi_edit"))
def put_device(body: UdiDeviceInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import udi

    return _rec(udi.put_device(ctx, a, body, if_match))


@router.get("/udi/parse", dependencies=P("view"))
def parse_code(code: str = Query(min_length=1, max_length=400)) -> JSONResponse:
    from .services import udi

    return _ok(udi.parse(code))


@router.post("/udi/devices/{udi_id}/approve", dependencies=P("view"))
def approve_device(udi_id: str, body: ApproveInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                   ) -> JSONResponse:
    from .services import udi

    return _signed(udi.approve_device(ctx, a, udi_id, body))


@router.get("/udi/exports", dependencies=P("udi_export"))
def list_exports(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import udi

    return _ok(udi.list_exports(ctx, limit, offset))


@router.post("/udi/exports", status_code=202, dependencies=P("udi_export"))
def create_export(body: UdiExportInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import udi

    return _ok(udi.create_export(ctx, a, body), 202)


@router.get("/udi/exports/{udi_export_id}", dependencies=P("udi_export"))
def get_export(udi_export_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import udi

    return _rec(udi.get_export(ctx, udi_export_id))


@router.get("/udi/exports/{udi_export_id}/download", dependencies=P("udi_export"))
def download_export(udi_export_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import udi

    return _file(udi.download_export(ctx, a, udi_export_id))


# ---------------------------------------------------------------- L1-L6 templates, assignments, printers

@router.get("/labels/templates", dependencies=P("view"))
def list_templates(code: str | None = Query(default=None, max_length=32), status: str | None = Status,
                   limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _ok(labels.list_templates(ctx, code, status, limit, offset))


@router.post("/labels/templates", status_code=201, dependencies=P("label_admin"))
def create_template(body: LabelTemplateInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                    ) -> JSONResponse:
    from .services import labels

    return _rec(labels.create_template(ctx, a, body), 201)


@router.get("/labels/templates/{label_template_id}", dependencies=P("view"))
def get_template(label_template_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.get_template(ctx, label_template_id))


@router.put("/labels/templates/{label_template_id}", dependencies=P("label_admin"))
def update_template(label_template_id: str, body: LabelTemplateInput, if_match: str | None = _if_match(),
                    a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.update_template(ctx, a, label_template_id, body, if_match))


@router.post("/labels/templates/{label_template_id}/new-version", status_code=201, dependencies=P("label_admin"))
def new_template_version(label_template_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                         ) -> JSONResponse:
    from .services import labels

    return _rec(labels.new_version(ctx, a, label_template_id), 201)


@router.get("/labels/templates/{label_template_id}/preview.svg", dependencies=P("view"))
def preview_template(label_template_id: str, item_id: str | None = Id(), lot_id: str | None = Id(),
                     lang: Literal["en", "fr"] | None = None, ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import labels

    out = labels.preview_svg(ctx, label_template_id, item_id, lot_id, lang)
    if isinstance(out, str):
        return Response(out, media_type="image/svg+xml")
    return _ok(out)


@router.get("/labels/assignments", dependencies=P("view"))
def list_assignments(item_id: str | None = Id(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _ok(labels.list_assignments(ctx, item_id))


@router.put("/labels/assignments", dependencies=P("label_admin"))
def put_assignments(body: AssignmentsInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                    ) -> JSONResponse:
    from .services import labels

    return _ok(labels.put_assignments(ctx, a, body))


@router.get("/labels/printers", dependencies=P("view"))
def list_printers(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _ok(labels.list_printers(ctx))


@router.post("/labels/printers", status_code=201, dependencies=P("label_admin"))
def create_printer(body: PrinterInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.create_printer(ctx, a, body), 201)


@router.put("/labels/printers/{printer_id}", dependencies=P("label_admin"))
def update_printer(printer_id: str, body: PrinterInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.update_printer(ctx, a, printer_id, body, if_match))


# ---------------------------------------------------------------- L7-L13 print jobs

@router.get("/labels/jobs", dependencies=P("view"))
def list_jobs(lot_id: str | None = Id(), wo_id: str | None = Id(), status: str | None = Status, limit: int = Limit(),
              offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _ok(labels.list_jobs(ctx, lot_id, wo_id, status, limit, offset))


@router.post("/labels/jobs", status_code=201, dependencies=P("label_print"))
def create_job(body: PrintJobInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.create_job(ctx, a, body), 201)


@router.get("/labels/jobs/{print_job_id}", dependencies=P("view"))
def get_job(print_job_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import labels

    return _rec(labels.get_job(ctx, print_job_id))


@router.get("/labels/jobs/{print_job_id}/output", dependencies=P("label_print"))
def job_output(print_job_id: str, reprint_reason: str | None = Query(default=None, max_length=500),
               qty: int | None = Query(default=None, ge=1, le=1_000_000), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import labels

    return _file(labels.output(ctx, a, print_job_id, reprint_reason, qty))


@router.post("/labels/jobs/{print_job_id}/events", dependencies=P("label_print"))
def job_event(print_job_id: str, body: PrintEventInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
              ) -> JSONResponse:
    from .services import labels

    return _rec(labels.add_event(ctx, a, print_job_id, body))


@router.post("/labels/jobs/{print_job_id}/verify", dependencies=P("label_print"))
def job_verify(print_job_id: str, body: VerifyInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
               ) -> JSONResponse:
    from .services import labels

    return _ok(labels.verify(ctx, a, print_job_id, body))


@router.post("/labels/jobs/{print_job_id}/reconcile", dependencies=P("label_print"))
def job_reconcile(print_job_id: str, body: ReconcileInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import labels

    return _signed(labels.reconcile(ctx, a, print_job_id, body))


@router.post("/labels/jobs/{print_job_id}/void", dependencies=P("label_print"))
def job_void(print_job_id: str, body: JobVoidInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
             ) -> JSONResponse:
    from .services import labels

    return _rec(labels.void_job(ctx, a, print_job_id, body))


# ---------------------------------------------------------------- Q1-Q5 validation package

@router.post("/validation/iq-check", dependencies=P("validation_admin"))
def iq_check(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valpkg

    return _ok(valpkg.iq_check(ctx))


@router.get("/validation/packages", dependencies=P("validation_view"))
def list_packages(kind: str | None = Status, limit: int = Limit(), offset: int = Offset(),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valpkg

    return _ok(valpkg.list_packages(ctx, kind, limit, offset))


@router.post("/validation/packages", status_code=202, dependencies=P("validation_admin"))
def create_package(body: PackageInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valpkg

    return _ok(valpkg.create_package(ctx, a, body), 202)


@router.get("/validation/packages/{package_id}", dependencies=P("validation_view"))
def get_package(package_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valpkg

    return _rec(valpkg.get_package(ctx, package_id))


@router.get("/validation/packages/{package_id}/download", dependencies=P("validation_view"))
def download_package(package_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import valpkg

    return _file(valpkg.download_package(ctx, a, package_id))


@router.post("/validation/packages/{package_id}/approve", dependencies=P("view"))
def approve_package(package_id: str, body: PkgApproveInput, a: Act = Depends(act),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valpkg

    return _signed(valpkg.approve_package(ctx, a, package_id, body))


@router.post("/validation/evidence", status_code=201, dependencies=P("validation_admin"))
async def upload_evidence(request: Request, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                          ) -> JSONResponse:
    """JSON body (`EvidenceInput`) or multipart with a JSON `file` plus `kind` / `title` form fields."""
    from starlette.concurrency import run_in_threadpool

    from .services import valpkg

    body = await valpkg.read_evidence(request)
    return _rec(await run_in_threadpool(valpkg.upload_evidence, ctx, a, body), 201)
