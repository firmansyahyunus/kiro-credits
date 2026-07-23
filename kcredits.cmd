@echo off
REM kcredits wrapper - runs the Python tool from anywhere.
REM %~dp0 = folder of this .cmd (with trailing backslash)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0kcredits.py" %*
) else (
  python "%~dp0kcredits.py" %*
)
