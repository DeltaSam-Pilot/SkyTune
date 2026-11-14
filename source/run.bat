@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 msfs_tweaker.py) || (python msfs_tweaker.py)
if errorlevel 1 pause
