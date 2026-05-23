$ErrorActionPreference = "Stop"

Write-Host "Starting JARVIS Backend + Ngrok Tunnel..." -ForegroundColor Cyan

$portInUse = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "Error: Port 8000 is already in use. Please kill the existing process." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Uvicorn backend on port 8000..."
Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", "cd backend; python main.py" -WindowStyle Normal

Write-Host "Waiting for backend to initialize..."
Start-Sleep -Seconds 3

Write-Host "Starting Ngrok tunnel..."
Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", "ngrok start jarvis --config=ngrok.yml" -WindowStyle Normal

Write-Host "`nJARVIS is now exposed to the internet!" -ForegroundColor Green
Write-Host "Check the Ngrok window for your public URL." -ForegroundColor Yellow
