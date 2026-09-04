@echo off
chcp 65001 >nul
rem ===========================================================================
rem 光影选片助手 —— 打包 Windows exe（PyInstaller 启动器，桌面软件形态）
rem 产物：dist\光影选片助手.exe，双击即启动原生桌面窗口（无浏览器、无控制台黑窗）
rem 说明：exe 是"启动器"形态——复用项目 .venv 环境（torch 等大依赖不重复打包），
rem       约 10MB，启动快、稳定；首次运行前请先完成 requirements.txt 依赖安装。
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 未找到 .venv，请先创建虚拟环境并安装依赖。
    pause
    exit /b 1
)

echo 打包中（约 1 分钟）…
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "光影选片助手" ^
    launcher.py

if exist "%~dp0dist\光影选片助手.exe" (
    echo.
    echo 完成：dist\光影选片助手.exe
    echo 复制该 exe 到项目根目录（与 app_qt.py 同级）即可双击使用。
) else (
    echo [错误] 打包失败，请查看上方报错。
)
pause
