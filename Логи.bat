@echo off
chcp 65001 >nul
title VKreger - логи
cd /d "%~dp0"
echo Последние сообщения системы ^(пришлите их, если что-то не работает^):
echo.
docker compose ps
echo.
docker compose logs --tail 80 backend worker frontend
pause
