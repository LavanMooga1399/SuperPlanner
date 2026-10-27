# Start one SuperPlanner job worker on Windows (PHASE2B 2.9). Needs $env:DATABASE_URL = "postgresql+psycopg://..."
# (JOB_BACKEND=queue, the default). In development the API also runs embedded worker threads (WORKER_EMBEDDED=auto).
# Extra arguments are passed on, e.g.  .\run_worker.ps1 --concurrency 1 --once   (Ctrl+C: graceful stop)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m superplanner.worker @args
exit $LASTEXITCODE
