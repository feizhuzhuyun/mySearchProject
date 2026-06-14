@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] 虚拟环境不存在，请先运行 setup.bat
    pause
    exit /b 1
)

start "" "venv\Scripts\pythonw.exe" "main.py"
