@echo off
REM Runs the daily credit snapshot for ALL projects and logs output.
REM Prefer the per-machine Python Launcher; fall back to python on PATH.
setlocal
if "%USERPROFILE%"=="" (
  echo [kcredits] USERPROFILE is not set; cannot select a private archive directory. 1>&2
  exit /b 1
)
set "KCREDITS_DATA_DIR=%USERPROFILE%\.kcredits"
if not exist "%KCREDITS_DATA_DIR%" mkdir "%KCREDITS_DATA_DIR%"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0kcredits.py" snapshot-all >> "%KCREDITS_DATA_DIR%\scheduled.log" 2>&1
) else (
  python "%~dp0kcredits.py" snapshot-all >> "%KCREDITS_DATA_DIR%\scheduled.log" 2>&1
)
endlocal
