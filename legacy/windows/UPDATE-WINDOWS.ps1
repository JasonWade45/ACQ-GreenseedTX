param(
    [string]$ExistingProject,
    [switch]$ConfirmStopped,
    [switch]$ApplyUpdate
)
$ErrorActionPreference = "Stop"
$Source = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')

try {
    if (-not $ExistingProject) {
        Add-Type -AssemblyName System.Windows.Forms
        $Dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $Dialog.Description = "Select the OLD project folder containing scripts, backend, data and .venv. Do not select the new release folder."
        $Dialog.ShowNewFolderButton = $false
        if ($Dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host "Cancelled. Nothing changed."; exit 0 }
        $ExistingProject = $Dialog.SelectedPath
    }
    $Target = [System.IO.Path]::GetFullPath($ExistingProject).TrimEnd('\')
    if ($Source -eq $Target) { throw "Extract this update into a NEW separate folder first. The old and new project folders must differ." }
    if (-not (Test-Path -LiteralPath (Join-Path $Target "scripts\manage.py"))) { throw "The selected folder is not an existing project root." }
    $Python = Join-Path $Target ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { throw "The old project's Python environment was not found. Use START-WINDOWS.cmd for a new installation, or select the correct old folder." }
    if (-not $ConfirmStopped -or -not $ApplyUpdate) {
        Add-Type -AssemblyName System.Windows.Forms
        $Message = "Stop the OLD app with Ctrl+C in every window first.`n`nUpdate program files in:`n$Target`n`nA database backup and copies of overwritten code will be made first. data, .env, .env.secrets and .venv are preserved. No CRM write or seller communication will occur.`n`nHave you stopped the app and do you approve this update?"
        $Choice = [System.Windows.Forms.MessageBox]::Show($Message,"Approve local application update",[System.Windows.Forms.MessageBoxButtons]::YesNo,[System.Windows.Forms.MessageBoxIcon]::Warning)
        if ($Choice -ne [System.Windows.Forms.DialogResult]::Yes) { Write-Host "Cancelled. Nothing changed."; exit 0 }
    }
    Set-Location -LiteralPath $Target
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupDir = Join-Path $Target "backups"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $DatabaseBackup = Join-Path $BackupDir ("before-v1.2-"+$Stamp+".db")
    & $Python (Join-Path $Target "scripts\manage.py") backup --output $DatabaseBackup
    if ($LASTEXITCODE -ne 0) { throw "Database backup failed. No program files were changed. Resolve the backup error first." }
    $CodeBackup = Join-Path $BackupDir ("code-before-v1.2-"+$Stamp)
    New-Item -ItemType Directory -Path $CodeBackup | Out-Null
    $Folders = @("backend\app","backend\migrations","backend\tests","backend\fixtures","frontend\src","frontend\e2e","frontend\dist","scripts","docs","examples")
    $Files = @("README.md","PROJECT_STATUS.md","LICENSE",".env.example",".gitignore","alembic.ini","pyproject.toml","backend\requirements.txt","backend\requirements-lock.txt","frontend\package.json","frontend\package-lock.json","frontend\index.html","frontend\vite.config.ts","frontend\eslint.config.js","frontend\playwright.config.ts","frontend\tsconfig.json","frontend\tsconfig.app.json","frontend\tsconfig.node.json","START-WINDOWS.cmd","UPDATE-WINDOWS.cmd","UPDATE-WINDOWS.ps1","START_HERE_WINDOWS_AR.md","MERGE-WORKSPACES.cmd","MERGE-WORKSPACES.ps1")
    $Candidates = @()
    foreach ($Folder in $Folders) {
        $Directory = Join-Path $Source $Folder
        if (Test-Path -LiteralPath $Directory) { $Candidates += Get-ChildItem -LiteralPath $Directory -File -Recurse }
    }
    foreach ($Name in $Files) {
        $File = Join-Path $Source $Name
        if (Test-Path -LiteralPath $File) { $Candidates += Get-Item -LiteralPath $File }
    }
    foreach ($File in $Candidates) {
        $Relative = $File.FullName.Substring($Source.Length).TrimStart('\')
        if ($Relative -match '(?i)(^|\\)(__pycache__|node_modules|data|\.venv|backups)(\\|$)' -or $File.Extension -in @('.pyc','.log','.bak') -or ($File.Name -like '.env*' -and $File.Name -ne '.env.example') -or $File.Name -eq '.preview-password') { continue }
        $Destination = Join-Path $Target $Relative
        if (Test-Path -LiteralPath $Destination) {
            $Previous = Join-Path $CodeBackup $Relative
            New-Item -ItemType Directory -Path (Split-Path $Previous -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $Destination -Destination $Previous
        }
        New-Item -ItemType Directory -Path (Split-Path $Destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $File.FullName -Destination $Destination -Force
    }
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $Target "backend\requirements-lock.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed. Database backup: $DatabaseBackup. Previous program files: $CodeBackup" }
    & $Python (Join-Path $Target "scripts\manage.py") migrate
    if ($LASTEXITCODE -ne 0) { throw "Migration failed. Do not delete data. Database backup: $DatabaseBackup. Previous program files: $CodeBackup" }
    & $Python (Join-Path $Target "scripts\manage.py") check
    if ($LASTEXITCODE -ne 0) { throw "Database validation failed. Keep the backup and inspect the error before starting." }
    Write-Host ""
    Write-Host "Update completed. Existing data and private configuration were preserved." -ForegroundColor Green
    Write-Host "Database recovery backup: $DatabaseBackup"
    Write-Host "Previous program files: $CodeBackup"
    Write-Host "Start from your OLD (now updated) project folder by double-clicking START-WINDOWS.cmd."
    Write-Host "Enter replacement API keys locally in Settings > Connections & AI."
} catch {
    Write-Host ("Update stopped: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
