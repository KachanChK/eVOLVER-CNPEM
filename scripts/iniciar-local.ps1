$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root '.local'
if (-not (Test-Path $python)) { throw 'Ambiente .venv ausente. Execute uv sync --all-packages.' }
if (-not (Test-Path (Join-Path $root 'backend\.env'))) { throw 'Configure backend/.env antes de iniciar.' }
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) { throw 'Execute npm ci na pasta frontend.' }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "A porta $port já está em uso. Encerre o processo existente antes de iniciar."
    }
}
$pythonArgument = '"' + $python + '"'
$api = Start-Process -FilePath $python -ArgumentList @('-m','dotenv','-f','backend/.env','run','--',$pythonArgument,'-m','uvicorn','evolver.api.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'api.log') -RedirectStandardError (Join-Path $logDir 'api-error.log')
$ingestion = Start-Process -FilePath $python -ArgumentList @('-m','dotenv','-f','backend/.env','run','--',$pythonArgument,'-m','evolver.ingestion') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'ingestao.log') -RedirectStandardError (Join-Path $logDir 'ingestao-error.log')
$ui = Start-Process -FilePath $npm -ArgumentList @('run','dev','--','--host','127.0.0.1','--strictPort') -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'interface.log') -RedirectStandardError (Join-Path $logDir 'interface-error.log')
@{ api = $api.Id; ingestao = $ingestion.Id; interface = $ui.Id } | ConvertTo-Json | Set-Content (Join-Path $logDir 'pids.json')
Write-Output 'Interface: http://127.0.0.1:5173'
Write-Output "Registros: $logDir"
