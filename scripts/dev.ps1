<#
.SYNOPSIS
  Two of Us - native Windows helper (PowerShell 5.1+ or 7+).

.DESCRIPTION
  For a checkout on the Windows filesystem, using Windows-native Node.js and uv.
  If you work inside WSL, use the Bash scripts instead (scripts/setup.sh,
  scripts/dev.sh). Do not share one checkout between Windows and WSL:
  backend\.venv and node_modules contain OS-specific binaries.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Setup
  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$Setup
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$env:NEXT_TELEMETRY_DISABLED = '1'

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $Hint"
    }
}

Assert-Command 'uv' 'Install uv: https://docs.astral.sh/uv/getting-started/installation/'
Assert-Command 'node' 'Install Node.js 24 LTS: https://nodejs.org/'
Assert-Command 'npm' 'npm ships with Node.js.'

$nodeVersion = (node --version).TrimStart('v').Split('.')
if ([int]$nodeVersion[0] -lt 20 -or ([int]$nodeVersion[0] -eq 20 -and [int]$nodeVersion[1] -lt 9)) {
    throw "Node.js >= 20.9 is required (found $(node --version))."
}

if ($Setup) {
    Push-Location $Backend
    try {
        uv sync --frozen
        uv run python -m app.cli.keys --init-env
        uv run alembic upgrade head
    } finally { Pop-Location }

    Push-Location $Frontend
    try { npm ci --no-audit --no-fund } finally { Pop-Location }

    Write-Host ''
    Write-Host 'Setup complete.'
    Write-Host '  1. Create the owner:  cd backend; uv run python -m app.cli.bootstrap_owner'
    Write-Host '  2. Start:             powershell -ExecutionPolicy Bypass -File scripts\dev.ps1'
    Write-Host '  3. Open exactly:      http://127.0.0.1:3000'
    return
}

Push-Location $Backend
try { uv run alembic upgrade head } finally { Pop-Location }

$backendArgs = @(
    'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000',
    '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1', '--no-access-log',
    '--reload', '--reload-dir', 'app'
)
$backendProc = Start-Process -FilePath 'uv' -ArgumentList $backendArgs -WorkingDirectory $Backend -NoNewWindow -PassThru
$frontendProc = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev') -WorkingDirectory $Frontend -NoNewWindow -PassThru

Write-Host 'Backend  http://127.0.0.1:8000/api/v1/docs (dev only)'
Write-Host 'App      http://127.0.0.1:3000   (press Ctrl+C to stop)'
try {
    while (-not $backendProc.HasExited -and -not $frontendProc.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($proc in @($backendProc, $frontendProc)) {
        if ($proc -and -not $proc.HasExited) {
            # Stop the whole process tree (uvicorn reloader, next dev workers).
            & taskkill.exe /PID $proc.Id /T /F | Out-Null
        }
    }
}
