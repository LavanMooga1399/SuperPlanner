# Start one SuperPlanner job worker on Windows (PHASE2B 2.9). Needs $env:DATABASE_URL = "postgresql+psycopg://..."
# (JOB_BACKEND=queue, the default with PostgreSQL). With SQLite no worker is needed: runs execute inside the API.
# Extra arguments are passed on, e.g.  .\run_worker.ps1 --concurrency 1 --once   (Ctrl+C: graceful stop)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m superplanner.worker @args
exit $LASTEXITCODE
