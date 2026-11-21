$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Ambiente .venv ausente. Execute uv sync --all-packages.' }
if (-not (Test-Path (Join-Path $root 'simulator\.env'))) { throw 'Configure simulator/.env antes de simular.' }
Push-Location $root
try {
    & $python -m evolver_simulator --env-file simulator/.env
    if ($LASTEXITCODE -ne 0) { throw 'O simulador não concluiu a execução.' }
} finally {
    Pop-Location
}
