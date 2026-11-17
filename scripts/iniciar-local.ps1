$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root '.local'
if (-not (Test-Path $python)) { throw 'Ambiente .venv ausente. Execute uv sync --all-packages.' }
if (-not (Test-Path (Join-Path $root 'backend\.env'))) { throw 'Configure backend/.env antes de iniciar.' }
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) { throw 'Execute npm ci na pasta frontend.' }
Get-Command npm.cmd -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "A porta $port já está em uso. Encerre o processo existente antes de iniciar."
    }
}
$serviceScript = Join-Path $PSScriptRoot 'servico-local.ps1'
foreach ($service in @('api', 'ingestao', 'interface')) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-NoProfile', '-File', ('"' + $serviceScript + '"'), $service) -WorkingDirectory $root -WindowStyle Normal
}
Write-Output 'Interface: http://127.0.0.1:5173'
Write-Output 'Para interromper um serviço, pressione Ctrl+C na janela correspondente.'
