param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('api', 'ingestao', 'interface')]
    [string]$Servico
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$Host.UI.RawUI.WindowTitle = "eVOLVER - $Servico"
Set-Location $root

Start-Transcript -Path (Join-Path $root ".local\$Servico.log") -Append | Out-Null
try {
    switch ($Servico) {
        'api' {
            & $python -m dotenv -f backend/.env run -- $python -m uvicorn evolver.api.main:app --host 127.0.0.1 --port 8000
        }
        'ingestao' {
            & $python -m dotenv -f backend/.env run -- $python -m evolver.ingestion
        }
        'interface' {
            Set-Location (Join-Path $root 'frontend')
            & npm.cmd run dev -- --host 127.0.0.1 --strictPort
        }
    }

    Write-Output "Serviço $Servico encerrado (código $LASTEXITCODE)."
} finally {
    Stop-Transcript | Out-Null
}
