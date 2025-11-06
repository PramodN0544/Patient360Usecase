param(
    [int]$Port = 8000,
    [switch]$Reload
)

# Ensure we run from the project folder that contains the `app` package
Set-Location $PSScriptRoot

Write-Host "Checking for existing uvicorn/python processes that reference 'app.main:app'..."
$uvProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'app.main:app' }

if ($uvProcs) {
    foreach ($p in $uvProcs) {
        Write-Host "Stopping PID $($p.ProcessId) - $($p.Name)"
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not stop PID $($p.ProcessId): $_"
        }
    }
} else {
    Write-Host "No existing uvicorn processes found."
}

$reloadArg = $null
if ($Reload) { $reloadArg = '--reload' }

Write-Host "Starting uvicorn app.main:app on 127.0.0.1:$Port (Reload: $($Reload.IsPresent))..."
# Run in foreground so logs appear in the terminal
python -m uvicorn app.main:app --host 127.0.0.1 --port $Port $reloadArg
