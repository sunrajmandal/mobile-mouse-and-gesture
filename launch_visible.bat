@echo off
title NeoPointer Control Server
cd /d "C:\Users\ASUS\.gemini\antigravity\scratch\ai_mouse_control"

echo.
echo  ========================================
echo   NeoPointer Bluetooth Control Server
echo  ========================================
echo.
echo  Starting server...
echo  Press Ctrl+C to stop.
echo.

"C:\Program Files\PyManager\python.exe" server.py

echo.
echo  Server stopped. Press any key to exit.
pause >nul
