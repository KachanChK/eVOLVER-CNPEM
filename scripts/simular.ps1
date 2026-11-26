[CmdletBinding(DefaultParameterSetName = 'Simulacao')]
param(
    [Parameter(ParameterSetName = 'Simulacao')]
    [switch]$Headless,
    [Parameter(ParameterSetName = 'ResetSqlite')]
    [switch]$ResetSqlite
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Ambiente .venv ausente. Execute uv sync --all-packages.' }
if (-not (Test-Path (Join-Path $root 'simulator\.env'))) { throw 'Configure simulator/.env antes de simular.' }
Push-Location $root
try {
    $mode = if ($ResetSqlite) { '--reset-sqlite' } elseif ($Headless) { '--headless' } else { '--test-center' }
    & $python -m evolver_simulator --env-file simulator/.env $mode
    if ($LASTEXITCODE -ne 0) {
        if ($ResetSqlite) { throw 'Falha ao limpar o SQLite do simulador.' }
        throw 'O simulador terminou com erro.'
    }
} finally {
    Pop-Location
}
