param([switch]$Api)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force logs,data\models | Out-Null
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot 'data\models'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '2'
$env:OLLAMA_CONTEXT_LENGTH = '8192'
$env:OLLAMA_NO_CLOUD = '1'
$env:PYTHONUTF8 = '1'
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 }
catch {
    $ollamaPath = Join-Path $projectRoot '.tools\ollama\ollama.exe'
    if (-not (Test-Path -LiteralPath $ollamaPath)) { throw 'Run scripts/setup.ps1 first.' }
    $process = Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden -WorkingDirectory $projectRoot -RedirectStandardOutput (Join-Path $projectRoot 'logs\ollama.out.log') -RedirectStandardError (Join-Path $projectRoot 'logs\ollama.err.log') -PassThru
    $process.Id | Set-Content (Join-Path $projectRoot 'logs\ollama.pid')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2; $ready = $true; break } catch {}
    }
    if (-not $ready) { throw 'Ollama did not start. See logs/ollama.err.log.' }
}
if ($Api) {
    & '.\.venv\Scripts\python.exe' -m uvicorn lab.api:app --host 127.0.0.1 --port 8000 --workers 1
} else {
    & '.\.venv\Scripts\python.exe' -m lab chat
}
