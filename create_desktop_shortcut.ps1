# Creates a one-click "GOLD SONIC" shortcut on the current user's Windows Desktop.
$Root = $PSScriptRoot
$PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
$MainPy  = Join-Path $Root "main.py"
$Icon    = Join-Path $Root "assets\gold_sonic.ico"

if (-not (Test-Path $PythonW)) {
    Write-Error "Virtual environment not found at $PythonW. Run setup first (py -3.12 -m venv .venv)."
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "GOLD SONIC.lnk"
$sc = $WshShell.CreateShortcut($ShortcutPath)
$sc.TargetPath = $PythonW
$sc.Arguments = "`"$MainPy`" --autostart --manage-sonic-pi"
$sc.WorkingDirectory = $Root
if (Test-Path $Icon) { $sc.IconLocation = "$Icon,0" }
$sc.Description = "GOLD SONIC — Live MT5 Gold Algorithmic Lo-fi Music Engine"
$sc.Save()

Write-Output "Created Desktop shortcut: $ShortcutPath"
