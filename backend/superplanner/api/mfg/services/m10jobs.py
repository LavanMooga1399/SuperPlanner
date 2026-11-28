"""M10 job kinds (M10-DESIGN 3): duty runs on `maintenance_runs`, resolved to their service bodies at call time."""

from __future__ import annotations

from typing import Any, Callable

#: kind -> (service module, function name); the function takes `{owner, params, kind}` and returns results
BODIES: dict[str, tuple[str, str]] = {
    "dhr_assemble": ("dhr", "assemble_job_body"), "batch_pack": ("coa", "pack_job_body"),
    "udi_export": ("udi", "export_job_body"), "label_send": ("labels", "send_job_body"),
    "validation_package": ("valpkg", "package_job_body"),
}


def handler(kind: str) -> Callable[..., None]:
    module, name = BODIES[kind]

    def run(ctx: Any, run_id: str, lease: Any) -> None:
        import importlib

        from ....integration.jobs import run_duty

        mod = importlib.import_module(f"{__package__}.{module}")
        body = getattr(mod, name)
        run_duty(ctx, run_id, lease, lambda info: body(ctx, info))

    return run
