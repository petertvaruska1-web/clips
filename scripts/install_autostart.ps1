# Registers ClipForge to start automatically when you log in to Windows (runs hidden, restarts on crash).
# Undo with: scripts\uninstall_autostart.ps1
$root = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m clipforge run" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "ClipForge" -Action $action -Trigger $trigger -Settings $settings `
  -Description "GTA 6 Twitch -> YouTube Shorts clipper" -Force | Out-Null
Write-Host "ClipForge will start automatically at login. Start it now with: Start-ScheduledTask ClipForge"
