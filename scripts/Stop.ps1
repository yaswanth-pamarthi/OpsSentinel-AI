$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$file=Join-Path $projectRoot 'storage/logs/processes.json'
if (Test-Path -LiteralPath $file) {
  $savedRecords=Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
      foreach ($record in $savedRecords) {
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$record.pid)
    if ($process) {
      $owned=$process.CommandLine -like ('*'+$projectRoot+'*')
      if ($owned) { taskkill /PID $record.pid /T /F | Out-Null }
    }
  }
}
Write-Host 'Project launcher processes stopped. Database volumes and Ollama are retained.'
