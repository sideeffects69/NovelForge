@echo off
REM ============================================================
REM  Puts a NovelForge shortcut, with the NovelForge logo, on
REM  your Desktop. Double-click it once; delete the shortcut
REM  any time - nothing else changes.
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make_shortcut.ps1"
echo.
pause
