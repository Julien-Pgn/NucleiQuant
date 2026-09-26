@echo off
rem Windows: double-click to start NucleiQuant.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher\start-nucleiquant.ps1"
if errorlevel 1 pause
