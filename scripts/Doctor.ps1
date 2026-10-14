$ErrorActionPreference='Continue'
$projectRoot=Split-Path -Parent $PSScriptRoot
py -3.12 --version
node --version
docker info --format '{{.ServerVersion}}'
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Select-Object -ExpandProperty models | Select-Object name,size } catch { Write-Host 'Ollama unavailable' }
try { Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 5 | Format-List } catch { Write-Host 'Backend unavailable' }
try { Write-Host ('Frontend HTTP status: '+(Invoke-WebRequest 'http://127.0.0.1:5174' -UseBasicParsing -TimeoutSec 5).StatusCode) } catch { Write-Host 'Frontend unavailable' }
