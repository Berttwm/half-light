@echo off
set HALFLIGHT_SYNC=1
title Half-Light SYNC
cd /d C:\Users\Bertrand\Desktop\dev\photo-showcase
echo Grading new photos...
python pipeline\build.py
if errorlevel 1 (
  color 4F
  echo.
  echo  SYNC FAILED - nothing was published. See site\photos\.log.jsonl
  pause
  exit /b 1
)
git add -A
git commit -m "sync: new photos" >nul 2>&1
git push
echo.
echo  DONE - Cloudflare deploys in about a minute.
pause
