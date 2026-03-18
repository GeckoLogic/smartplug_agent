# run_agent.ps1 - Wrapper invoked by the Windows Scheduled Task.
# Runs the Smart Plug Agent and appends timestamped output to run.log.
# Log is rotated (kept as run.log.1) once it exceeds 1 MB.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ScriptDir "venv\Scripts\python.exe"
$AgentScript = Join-Path $ScriptDir "agent.py"
$ConfigFile = Join-Path $ScriptDir "config.yaml"
$StateFile = Join-Path $ScriptDir "state.json"
$LogFile = Join-Path $ScriptDir "run.log"

# Rotate log when it exceeds 1 MB
if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 1MB) {
    Move-Item $LogFile "$LogFile.1" -Force
}

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"=== Run started $Timestamp ===" | Add-Content $LogFile

$Output = & $PythonExe $AgentScript --config $ConfigFile --state $StateFile 2>&1
$Output | Add-Content $LogFile

$ExitCode = $LASTEXITCODE
"=== Finished with exit code $ExitCode ===" | Add-Content $LogFile

exit $ExitCode
