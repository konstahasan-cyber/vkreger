@echo off
chcp 65001 >nul
title VKreger - остановка
cd /d "%~dp0"
docker compose down
echo.
echo VKreger остановлен. Данные сохранены - при следующем запуске всё будет на месте.
pause
