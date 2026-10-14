$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $projectRoot 'backend')
try { & .venv/Scripts/python.exe -m pytest -q; if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' } } finally { Pop-Location }
Push-Location (Join-Path $projectRoot 'frontend')
try { npm test; if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' } } finally { Pop-Location }
