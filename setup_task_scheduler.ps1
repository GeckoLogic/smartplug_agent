# setup_task_scheduler.ps1
# Registers a Windows Scheduled Task that runs the Smart Plug Agent every 5 minutes.
# Run once from a PowerShell prompt in the project directory:
#
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # (one-time, if needed)
#   .\setup_task_scheduler.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerScript = Join-Path $ScriptDir "run_agent.vbs"
$TaskName = "SmartPlugAgent"

# ── Prerequisite checks ────────────────────────────────────────────────────────

if (-not (Test-Path (Join-Path $ScriptDir "venv\Scripts\python.exe"))) {
    Write-Error @"
Virtual environment not found.
Run the following first:
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
"@
    exit 1
}

if (-not (Test-Path (Join-Path $ScriptDir "config.yaml"))) {
    Write-Error @"
config.yaml not found.
Copy the example and fill in your credentials:
    Copy-Item config.yaml.example config.yaml
"@
    exit 1
}

# ── Build task components ──────────────────────────────────────────────────────

# Action: run run_agent.ps1 via powershell.exe
$Action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$RunnerScript`"" `
    -WorkingDirectory $ScriptDir

# Trigger: every 5 minutes, effectively forever (10 years), starting now.
# StartWhenAvailable (in Settings) handles the Persistent=true equivalent:
# if the machine was off during a scheduled run, it catches up on next startup.
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RunOnlyIfNetworkAvailable `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -Hidden

# ── Register (replace if already exists) ──────────────────────────────────────

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Replaced existing '$TaskName' task."
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Limited `
    -Description "Monitors Meross smart plugs every 5 minutes and sends alerts on issues."

Write-Host ""
Write-Host "Registered '$TaskName' - runs every 5 minutes, logs to run.log."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Run now:     Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  View logs:   Get-Content run.log -Tail 50 -Wait"
Write-Host "  Task status: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host ('  Remove:      Unregister-ScheduledTask -TaskName ' + "'$TaskName'" + ' -Confirm:$false')
