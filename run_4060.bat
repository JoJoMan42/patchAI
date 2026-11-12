@echo off
title PatchAI v2 - training and evaluation (do not close this window)
echo ============================================================
echo  PatchAI v2: training + evaluation on this laptop
echo  Takes about 4-5 hours. Keep the laptop plugged in.
echo  Do NOT close this window until it says DONE or STOPPED.
echo ============================================================
echo.

rem Stop Windows from sleeping while plugged in (it would pause the training).
powercfg /change standby-timeout-ac 0 >nul 2>&1
echo Sleep while plugged in: turned off.
echo.

rem Everything else runs inside WSL Ubuntu, in ~/patchAI:
rem   1. get the latest code
rem   2. start Ollama if it isn't running
rem   3. run run_4060.sh (pass --dpo to this file for the bonus step)
wsl -e bash -lc "set -e; cd ~/patchAI || { echo 'STOPPED: ~/patchAI not found in WSL'; exit 1; }; echo 'Getting the latest code...'; git pull --no-edit https://github.com/JoJoMan42/patchAI.git main; if ! curl -sf http://localhost:11434/api/tags >/dev/null; then echo 'Starting Ollama...'; nohup ollama serve > ~/ollama.log 2>&1 & sleep 8; fi; source .venv/bin/activate; bash run_4060.sh %*"

echo.
echo ============================================================
echo  Finished. Scroll up: it should say DONE (or STOPPED + a log file).
echo ============================================================
pause
