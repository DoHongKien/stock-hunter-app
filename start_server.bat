@echo off
chcp 65001 >nul
title Thợ Săn Điểm Vào — Mobile API Server

echo.
echo  ██████████████████████████████████████████
echo  █  🏹 THỢ SĂN ĐIỂM VÀO — MOBILE SERVER  █
echo  ██████████████████████████████████████████
echo.

cd /d "%~dp0"

:: Kiểm tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LỖI] Không tìm thấy Python! Vui lòng cài đặt Python 3.9+
    pause & exit /b 1
)

:: Cài đặt thư viện nếu chưa có
echo [1/3] Kiểm tra thư viện...
pip install -r api\requirements.txt -q --disable-pip-version-check

echo [2/3] Khởi động API Server...
echo.
echo  📱 Truy cập app trên điện thoại:
echo     Bước 1: Kết nối điện thoại cùng WiFi với máy tính này
echo.

:: Lấy IP máy tính
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%A
    goto :found_ip
)
:found_ip
set IP=%IP: =%
echo     Bước 2: Mở trình duyệt trên điện thoại, vào địa chỉ:
echo     👉  http://%IP%:8000/app/
echo.
echo     Bước 3: Cài đặt API URL trong app: http://%IP%:8000
echo.
echo  💻 Hoặc truy cập trên máy tính:
echo     👉  http://localhost:8000/app/
echo.
echo  ═══════════════════════════════════════════
echo  Nhấn Ctrl+C để dừng server
echo  ═══════════════════════════════════════════
echo.

[3/3] Chạy server...
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

pause
