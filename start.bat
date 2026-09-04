@echo off
chcp 65001 >nul
rem ===========================================================================
rem 光影选片助手 Smart Cull Assistant —— 一键启动脚本（Windows）
rem
rem 功能：
rem   1. 优先使用项目内 .venv 的 python（若存在）；否则用系统 python
rem   2. 把 HF/TORCH 模型缓存重定向到项目内目录（.hf_cache / .torch_cache），
rem      不落 C 盘，便于携带与清理
rem   3. 启动 Streamlit（深色主题，默认 http://localhost:8501）
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHON_CMD="
if exist "%VENV_PY%" (
    set "PYTHON_CMD=%VENV_PY%"
) else (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)
if "%PYTHON_CMD%"=="" (
    echo [错误] 未找到 Python：请先安装 Python 3.10+，或创建项目 .venv 后重试。
    pause
    exit /b 1
)

rem 模型与依赖缓存重定向到项目内（不落 C 盘）
set "HF_HOME=%~dp0.hf_cache"
set "HF_HUB_CACHE=%~dp0.hf_cache\hub"
set "TORCH_HOME=%~dp0.torch_cache"
set "TRANSFORMERS_CACHE=%~dp0.hf_cache\hub"
set "PYTHONPYCACHEPREFIX=%~dp0.pycache"

echo.
echo ============================================================
echo   光影选片助手 Smart Cull Assistant
echo   使用解释器: %PYTHON_CMD%
echo   模型缓存  : %HF_HOME%
echo   启动后请用浏览器访问: http://localhost:8501
echo ============================================================
echo.

"%PYTHON_CMD%" -m streamlit run app.py

echo.
echo Streamlit 已退出。
pause
