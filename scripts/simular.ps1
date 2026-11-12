$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Ambiente .venv ausente. Execute uv sync --all-packages.' }
if (-not (Test-Path (Join-Path $root 'simulator\.env'))) { throw 'Configure simulator/.env antes de simular.' }
try {
    $experiments = Invoke-RestMethod 'http://127.0.0.1:8000/api/experiments'
} catch {
    throw 'A API não está acessível. Inicie os serviços antes de executar o simulador.'
}
$active = @($experiments | Where-Object { $_.status -eq 'active' })
$vials = @($active | ForEach-Object { $_.vial_id } | Sort-Object -Unique)
if ($vials.Count -eq 0) { throw 'Crie um experimento ativo na interface antes de executar o simulador.' }
$previous = $env:SIMULATOR_VIAL_IDS
$previousExperiments = $env:SIMULATOR_EXPERIMENT_IDS
try {
    $env:SIMULATOR_VIAL_IDS = $vials -join ','
    $allocations = @{}
    foreach ($experiment in $active) { $allocations[[string]$experiment.vial_id] = [long]$experiment.id }
    $env:SIMULATOR_EXPERIMENT_IDS = ConvertTo-Json -InputObject $allocations -Compress
    Write-Output "Simulando os vials ativos: $env:SIMULATOR_VIAL_IDS"
    Set-Location $root
    & $python -m dotenv -f simulator/.env run --no-override -- $python -m evolver_simulator
    if ($LASTEXITCODE -ne 0) { throw 'O simulador não concluiu a execução.' }
} finally {
    $env:SIMULATOR_VIAL_IDS = $previous
    $env:SIMULATOR_EXPERIMENT_IDS = $previousExperiments
}
