@echo off
chcp 65001 >nul
title VKreger - запуск
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo [!] Docker не найден. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [!] Создан файл .env. Заполните его ^(SECRET_KEY, ENCRYPTION_KEYS, ADMIN_EMAIL, ADMIN_PASSWORD, OPENAI_API_KEY^),
  echo     сохраните, закройте Блокнот и снова запустите этот файл.
  notepad ".env"
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Запускаю Docker Desktop...
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  ) else (
    echo [!] Откройте Docker Desktop вручную.
  )
  echo Жду, пока Docker будет готов ^(до пары минут^)...
)
:wait_docker
docker info >nul 2>&1
if errorlevel 1 (
  timeout /t 3 /nobreak >nul
  goto wait_docker
)

echo Запускаю VKreger ^(первый раз сборка займёт 5-15 минут^)...
docker compose up -d --build
if errorlevel 1 (
  echo [!] Не удалось запустить. Посмотрите ошибки выше или запустите "Логи.bat".
  pause
  exit /b 1
)

echo Жду, пока панель откроется...
:wait_panel
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://localhost:3000/login).StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  timeout /t 3 /nobreak >nul
  goto wait_panel
)

start "" http://localhost:3000
echo.
echo Готово! Панель открыта: http://localhost:3000
echo Это окно можно закрыть - панель продолжит работать.
timeout /t 10
