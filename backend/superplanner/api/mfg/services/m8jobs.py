"""M8 job kinds (M8-DESIGN 3): duty runs on `maintenance_runs`, resolved to their service bodies at call time."""

from __future__ import annotations

from typing import Any, Callable

#: kind -> (service module, function name); the function takes `{owner, params, kind}` and returns results
BODIES: dict[str, tuple[str, str]] = {
    "forecast_run": ("forecast", "run_job_body"), "history_refresh": ("forecast", "refresh_job_body"),
    "ss_run": ("invopt", "run_job_body"), "rate_run": ("rate", "run_job_body"), "ster_plan": ("ster", "plan_job_body"),
    "nightly_plan": ("planning", "nightly_job_body"), "sap_sync": ("sap", "sync_job_body"),
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
