@echo off
setlocal

echo Starting JARVIS Backend + Ngrok Tunnel...

netstat -ano | findstr :8000 | findstr LISTENING >nul
if %ERRORLEVEL% equ 0 (
    echo Port 8000 is already in use. Please kill the existing process.
    exit /b 1
)

echo Starting Uvicorn backend on port 8000...
start "JARVIS Backend" cmd /c "cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

echo Waiting for backend to initialize...
timeout /t 3 /nobreak >nul

echo Starting Ngrok tunnel...
start "JARVIS Ngrok Tunnel" cmd /c "ngrok start jarvis --config=ngrok.yml"

echo.
echo JARVIS is now exposed to the internet!
echo Check the Ngrok window for your public URL.
pause
