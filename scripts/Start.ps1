$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$logRoot=Join-Path $projectRoot 'storage/logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
Push-Location $projectRoot
try {
  docker compose up -d --wait db
  if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and retry.' }
  $ollama=Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
  try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null } catch {
    if (-not (Test-Path $ollama)) { throw 'Ollama is missing. Install it and pull qwen3:1.7b and nomic-embed-text.' }
    Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
  }
  Push-Location backend
  try { & .venv/Scripts/python.exe -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Migration failed' } } finally { Pop-Location }
  $records=@()
  $apiReady=$false
  try { $response=Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 3; $apiReady=$response.status -eq 'ok' } catch {}
  if (-not $apiReady) {
    $process=Start-Process -FilePath (Join-Path $projectRoot 'backend/.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001' -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'api.stdout.log') -RedirectStandardError (Join-Path $logRoot 'api.stderr.log') -PassThru
    $records+=@{pid=$process.Id;kind='backend'}
  }
  $uiReady=$false
  try { Invoke-WebRequest 'http://127.0.0.1:5174' -UseBasicParsing -TimeoutSec 3 | Out-Null; $uiReady=$true } catch {}
  if (-not $uiReady) {
    $node=(Get-Command node).Source
    $viteEntry='"'+(Join-Path $projectRoot 'frontend/node_modules/vite/bin/vite.js')+'"'
        $process=Start-Process -FilePath $node -ArgumentList $viteEntry,'--host','127.0.0.1','--port','5174','--strictPort' -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'ui.stdout.log') -RedirectStandardError (Join-Path $logRoot 'ui.stderr.log') -PassThru
    $records+=@{pid=$process.Id;kind='frontend'}
  }
  if ($records.Count -gt 0) { $records | ConvertTo-Json | Set-Content (Join-Path $logRoot 'processes.json') }
  Write-Host 'UI: http://localhost:5174'
  Write-Host 'API documentation: http://127.0.0.1:8001/docs'
  Write-Host 'Accounts and password: LOGIN.txt'
} finally { Pop-Location }
