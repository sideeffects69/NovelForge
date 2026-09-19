# Creates a NovelForge shortcut (with the logo) that starts the app with no console window.
# Run it through "Make Desktop Shortcut.bat", or: powershell -File tools\make_shortcut.ps1 [-Folder <dir>]
param([string]$Folder = [Environment]::GetFolderPath("Desktop"))

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($found) { $pythonw = $found.Source }
}
if (-not (Test-Path $pythonw)) {
    Write-Host "Could not find Python (pythonw.exe). Install Python 3.13 or newer first."
    exit 1
}

$icon = Join-Path $repo "brand\icon.ico"
$link = Join-Path $Folder "NovelForge.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m novelforge"
$shortcut.WorkingDirectory = $repo
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "NovelForge - a local novel-writing studio"
$shortcut.Save()
Write-Host "Created $link"
