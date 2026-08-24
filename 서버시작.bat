@echo off
rem === K-TEST scoring server + cloudflared tunnel ===
rem Paths derive from %~dp0 so the Korean folder name never breaks batch parsing.
set ROOT=%~dp0

start "K-TEST Server" /d "%ROOT%assessment" cmd /k ""%ROOT%.venv\Scripts\python.exe" -m uvicorn src.api:app --host 127.0.0.1 --port 8000"

timeout /t 4 /nobreak > nul

start "Tunnel" cmd /k ""%ROOT%tools\cloudflared.exe" tunnel --url http://127.0.0.1:8000"

rem === self-check: is the LoRA STT server actually up? ===
rem The scoring server only knows the ADDRESS of the LoRA server, not whether it
rem answers. If .env says provider=lora and that server is down, every speaking
rem answer fails with 503 while everything looks fine here. So we knock once and
rem warn. We never block startup: writing answers score without LoRA.
set ENVFILE=%ROOT%assessment\.env
set LORA_URL=
rem 2^>nul keeps the "file not found" noise away when .env is absent (a fresh clone).
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"LORA_STT_URL=" "%ENVFILE%" 2^>nul`) do set LORA_URL=%%B
findstr /b /c:"KTEST_STT_PROVIDER=lora" "%ENVFILE%" >nul 2>&1
if not errorlevel 1 (
  if defined LORA_URL (
    rem -f makes an HTTP error (4xx/5xx) count as "not usable", same rule the
    rem scoring server's ping() uses. -m 2 keeps this check under two seconds.
    curl -f -s -m 2 -o nul "%LORA_URL%/health"
    if errorlevel 1 (
      echo.
      echo [WARN] .env says KTEST_STT_PROVIDER=lora, but the LoRA STT server
      echo        at %LORA_URL% did not answer /health within 2 seconds.
      echo        Speaking answers will fail with 503 until it is running.
      echo        Writing answers are unaffected - startup continues.
      echo        Check with: GET /health  ^(stt_available / stt_detail^)
    ) else (
      echo.
      echo [OK] LoRA STT server answered at %LORA_URL%
    )
  ) else (
    echo.
    echo [WARN] KTEST_STT_PROVIDER=lora but LORA_STT_URL is missing in .env
  )
)

echo.
echo Two windows opened.
echo In the [Tunnel] window, copy the https://XXXX.trycloudflare.com address
echo and give it to the backend team as ASSESSMENT_URL.
echo.
pause
