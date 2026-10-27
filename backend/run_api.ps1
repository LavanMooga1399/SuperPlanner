# Start the SuperPlanner API on Windows (ARCHITECTURE 18, PHASE2B 5.6). Same settings as run_api.sh:
# DATABASE_URL, HOST, PORT, CORS_ORIGINS, RUN_WORKERS, LOG_FORMAT, FORWARDED_ALLOW_IPS, ...
# PostgreSQL only: $env:DATABASE_URL is required, and the schema must be at head first
#   .\.venv\Scripts\python.exe -m superplanner.migrate upgrade     (or $env:AUTO_MIGRATE = "true" for local dev)
# Local development: $env:APP_ENV = "development" (default is production with its secure-default checks).
# Extra arguments are passed on to uvicorn, e.g.  .\run_api.ps1 --reload        (Ctrl+C stops it)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$apiHost = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$port = if ($env:PORT) { $env:PORT } else { "8000" }
$fwd = if ($env:FORWARDED_ALLOW_IPS) { $env:FORWARDED_ALLOW_IPS } else { "127.0.0.1" }
$uvArgs = @("-m", "uvicorn", "superplanner.api.main:app", "--host", $apiHost, "--port", $port,
            "--proxy-headers", "--forwarded-allow-ips", $fwd)
# With JSON logs the API writes its own http.request access line (with request id).
if ($env:LOG_FORMAT -eq "json") { $uvArgs += "--no-access-log" }
& $py @uvArgs @args
exit $LASTEXITCODE
