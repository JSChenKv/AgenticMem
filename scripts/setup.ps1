$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv --without-pip .venv }
python -m pip --python '.venv\Scripts\python.exe' install pip -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (-not (Test-Path '.tools\ollama\ollama.exe')) {
    New-Item -ItemType Directory -Force .tools | Out-Null
    Invoke-WebRequest 'https://github.com/ollama/ollama/releases/download/v0.40.6/ollama-windows-amd64.zip' -OutFile '.tools\ollama-windows-amd64.zip'
    Expand-Archive -LiteralPath '.tools\ollama-windows-amd64.zip' -DestinationPath '.tools\ollama'
}
# Start only the model service; start.ps1 without -Api opens interactive chat.
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot 'data\models'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '2'
$env:OLLAMA_CONTEXT_LENGTH = '8192'
$env:OLLAMA_NO_CLOUD = '1'
New-Item -ItemType Directory -Force logs,data\models | Out-Null
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 }
catch {
    $process = Start-Process -FilePath (Join-Path $projectRoot '.tools\ollama\ollama.exe') -ArgumentList 'serve' -WindowStyle Hidden -WorkingDirectory $projectRoot -RedirectStandardOutput (Join-Path $projectRoot 'logs\ollama.out.log') -RedirectStandardError (Join-Path $projectRoot 'logs\ollama.err.log') -PassThru
    $process.Id | Set-Content 'logs\ollama.pid'
    Start-Sleep -Seconds 3
}
foreach ($model in @('qwen2.5:7b', 'bge-m3:latest')) {
    & '.\.tools\ollama\ollama.exe' pull $model
    if ($LASTEXITCODE -ne 0) { throw "Model download failed: $model" }
}
$env:HF_HUB_OFFLINE = '0'
& '.\.venv\Scripts\python.exe' -c 'from lab.core import ROOT; from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name="Qdrant/bm25"); print("Local BM25 cache ready")'
Remove-Item Env:\HF_HUB_OFFLINE
if ($LASTEXITCODE -ne 0) { throw 'BM25 cache setup failed.' }
python -m pip --python '.venv\Scripts\python.exe' freeze | Set-Content -Encoding utf8 requirements.lock.txt
Write-Host 'Ready. Run .\scripts\start.ps1 for chat or .\scripts\start.ps1 -Api for REST API.'
