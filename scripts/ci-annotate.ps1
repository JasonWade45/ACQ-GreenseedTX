# Turn the last lines of a captured build log into GitHub annotations, so a
# failure on the Windows runner explains itself in the run summary instead of
# hiding in a log file.
param([string]$Path, [int]$Lines = 12)

if (-not (Test-Path $Path)) { Write-Host "::error::No build log was captured"; return }

foreach ($line in (Get-Content $Path -Tail $Lines)) {
  if ([string]::IsNullOrWhiteSpace($line)) { continue }
  $safe = $line -replace '%', '%25' -replace "`r", '%0D' -replace "`n", '%0A'
  if ($safe.Length -gt 800) { $safe = $safe.Substring(0, 800) }
  Write-Host "::error title=Build failed::$safe"
}
