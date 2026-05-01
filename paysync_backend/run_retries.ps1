# run_retries.ps1
# Called by Windows Task Scheduler every minute

$projectPath = "C:\Projects\paysync"
$pythonPath  = "$projectPath\venv\Scripts\python.exe"
$managePath  = "$projectPath\manage.py"
$logPath     = "$projectPath\retry_scheduler.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

try {
    $output = & $pythonPath $managePath process_retries 2>&1
    Add-Content -Path $logPath -Value "[$timestamp] SUCCESS: $output"
}
catch {
    Add-Content -Path $logPath -Value "[$timestamp] ERROR: $_"
}