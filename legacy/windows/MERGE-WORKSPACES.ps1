param([string]$SourceDatabase)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
try {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { throw "Start this new/unified release once with START-WINDOWS.cmd first, then stop it with Ctrl+C. Python dependencies must be installed before preparing a review." }
    Add-Type -AssemblyName System.Windows.Forms
    $Choice = [System.Windows.Forms.MessageBox]::Show("Stop BOTH old apps with Ctrl+C first.`n`nPrepare a consistent, read-only snapshot of the GitHub database and back up this unified workspace. Originals are preserved. No records are merged until you review and approve in Import Center. No keys or company database uploads are needed.`n`nHave both apps been stopped, and do you approve preparing this LOCAL review?", "Prepare both-workspace migration", [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Warning)
    if ($Choice -ne [System.Windows.Forms.DialogResult]::Yes) { Write-Host "Cancelled. Nothing changed."; exit 0 }
    if (-not $SourceDatabase) {
        $Picker = New-Object System.Windows.Forms.OpenFileDialog
        $Picker.Title = "Select the GITHUB / NEXT project's backend\acquisitions.db (not unified data\acquisitions.db)"
        $Picker.Filter = "SQLite database (*.db;*.sqlite;*.sqlite3)|*.db;*.sqlite;*.sqlite3|All files (*.*)|*.*"
        $Picker.CheckFileExists = $true
        if ($Picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host "Cancelled. Nothing changed."; exit 0 }
        $SourceDatabase = $Picker.FileName
    }
    & $Python (Join-Path $Root "scripts\merge_workspaces.py") --source $SourceDatabase
    if ($LASTEXITCODE -ne 0) { throw "Review preparation failed. Keep both databases and the error above. Do not replace or reset either database." }
    Write-Host ""
    Write-Host "Review is prepared, not committed. Start START-WINDOWS.cmd and open Import Center." -ForegroundColor Green
    Write-Host "Review each seller: keep separate, link after identity verification, or skip. Never link people only because they share a property."
    Write-Host "Keep the original folders and private data\workspace-merges snapshots until you have verified the final data."
} catch {
    Write-Host ("Local migration preparation stopped: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
