$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
  py -3.12 scripts/configure.py
  if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 configuration failed' }
  if (-not (Test-Path 'backend/.venv/Scripts/python.exe')) { py -3.12 -m venv backend/.venv }
  & backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
  if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' }
  docker compose up -d --wait db
  if ($LASTEXITCODE -ne 0) { throw 'Database startup failed. Start Docker Desktop first.' }
  Push-Location backend
  try { & .venv/Scripts/python.exe -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' } } finally { Pop-Location }
  Push-Location frontend
  try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' } } finally { Pop-Location }
  & backend/.venv/Scripts/python.exe scripts/seed.py
  if ($LASTEXITCODE -ne 0) { throw 'Seeding failed. Verify Ollama and the two downloaded models.' }
  Write-Host 'Setup completed. Use scripts/Start.ps1 and read LOGIN.txt.'
} finally { Pop-Location }
