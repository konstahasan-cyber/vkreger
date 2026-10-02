# VKreger — AI-платформа для сообществ ВКонтакте

Панель для автоматизированного создания, оформления и ведения VK-сообществ с помощью OpenAI.
Вы добавляете свои VK-аккаунты (к каждому при желании привязываете отдельный proxy), создаёте
проект с описанием бизнеса, города, ЦА и цели. Дальше система:

1. анализирует бизнес (AI STRATEGIST) и показывает **Preview**: варианты названия, описание, статус,
   оформление, рубрики, стратегию, закреплённый пост;
2. по кнопке «Создать» создаёт новое сообщество через `groups.create` или подключает существующее;
3. заполняет настройки (`groups.edit`, `status.set`), публикует и закрепляет пост;
4. строит контент-план и первую очередь публикаций; посты пишет связка COPYWRITER + EDITOR + IMAGE_PROMPT,
   есть анти-повторы и картинки;
5. сам публикует посты по расписанию, с ретраями и без дублей;
6. принимает комментарии и сообщения (Callback API / Long Poll), классифицирует их
   (QUESTION / LEAD / NEGATIVE / SPAM / OTHER), готовит ответы (`AUTO_REPLY = OFF / APPROVAL / AUTO`),
   создаёт лиды и уведомляет оператора;
7. собирает статистику и периодически корректирует стратегию (AI ANALYST);
8. учитывает расходы OpenAI по каждому вызову и останавливает дорогие автоматические задачи при
   превышении лимитов.

Архитектура, схема БД и TODO описаны в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

> Используются только официальные методы VK API. В системе нет обхода CAPTCHA, антибот-защиты и
> лимитов VK, нет подмены fingerprint и автоматической регистрации аккаунтов. Proxy — это только
> сетевая конфигурация ваших собственных аккаунтов.

## Стек

* **Backend:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis, Celery (worker + beat)
* **AI:** OpenAI Responses API (Structured Outputs), Embeddings, Images (`gpt-image-*`); модели задаются в конфиге
* **Frontend:** Next.js 16 (App Router) + TypeScript
* **Запуск:** Docker Compose

## Быстрый старт

```bash
cp .env.example .env
# обязательно заполните SECRET_KEY, ENCRYPTION_KEYS, ADMIN_PASSWORD, POSTGRES_PASSWORD, OPENAI_API_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                  # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"     # ENCRYPTION_KEYS
docker compose up -d --build
```

* Панель: http://localhost:3000 (вход: `ADMIN_EMAIL` / `ADMIN_PASSWORD`, владелец создаётся при первом старте).
* API и Swagger: http://localhost:8000/api/docs
* Миграции применяются автоматически при старте контейнера `backend` (`alembic upgrade head`).

Без ключа OpenAI можно попробовать систему с `AI_PROVIDER=fake` и `IMAGE_PROVIDER=fake`:
офлайн-провайдер возвращает детерминированные ответы, и весь пайплайн работает.

## Настройка VK

1. **Токен аккаунта.** Создайте своё приложение VK (VK ID) и получите user access token с правами
   `wall, groups, photos, stats, offline` (для сообщений — ещё `messages`). В разделе «VK Accounts»
   нажмите «Добавить аккаунт» и вставьте токен. Система проверит его через `users.get` и загрузит
   список сообществ, где вы администратор (`groups.get?filter=admin`).
2. **Proxy (необязательно).** В разделе «Proxies» загрузите список в любом формате
   (`IP:PORT:LOGIN`, `LOGIN@IP`, `http://LOGIN:PASSWORD@IP:PORT`, `socks5://LOGIN@IP`, …) и привяжите
   proxy к аккаунту. Если proxy умер, аккаунт автоматически получает свободный живой proxy (можно
   отключить). Если замены нет, запросы **не** уходят напрямую: задача останавливается с ошибкой.
3. **Ключ сообщества** (Управление → Работа с API → Ключи доступа) нужен для отправки сообщений
   и Long Poll. Укажите его в «Communities» или при подключении сообщества.
4. **События.** На странице «Communities» выберите:
   * *Callback API*: нужен публичный `PUBLIC_BASE_URL`, сервер регистрируется автоматически
     (`groups.addCallbackServer`); подтверждение и проверка `secret` встроены;
   * *Long Poll*: работает без публичного адреса, нужен ключ сообщества.

## OpenAI и расходы

* `OPENAI_API_KEY` задаётся только через переменные окружения.
* Модель по умолчанию — `AI_DEFAULT_MODEL`. Для отдельных операций её можно переопределить в
  `AI_MODEL_OVERRIDES` (`project_setup`, `content_plan`, `post_compose`, `post_edit`, `image_prompt`,
  `analytics_review`, `inbox_triage`). Значения меняются в «AI Settings» без перезапуска.
* Каждый вызов пишется в `ai_usage`: model, input/cached/output tokens, estimated_cost, project_id,
  operation, created_at. Цены за 1M токенов задаются в `AI_PRICING_JSON` (встроены значения по
  умолчанию; сверьте их с актуальным прайсом OpenAI).
* `MAX_AI_COST_PER_DAY` и `MAX_AI_COST_PER_PROJECT_DAY`: при превышении автоматические задачи
  (автопилот, ANALYST, авто-ответы) останавливаются. Ручные операции может принудительно
  запустить только администратор (`force`).
* Экономия токенов: в запрос уходят только нужные блоки `project_context`, `brand_context`,
  `content_rules`, `recent_posts_summary`, `analytics_summary`. Операции объединены, где это возможно
  (например, пост + редактура + промпт картинки — один вызов), а для prompt caching передаётся
  `prompt_cache_key`.

## Безопасность

* VK-токены, ключи сообществ, callback secret и пароли proxy хранятся в БД зашифрованными (Fernet,
  ротация через `ENCRYPTION_KEYS`). API их не возвращает: пароль proxy показывается маской.
* Токен VK передаётся в теле POST, а не в URL. Логи проходят фильтр, который вычищает токены, пароли и ключи.
* JWT-аутентификация, роли `owner / admin / operator / viewer` (`app/core/rbac.py`), аудит всех
  административных действий (`audit_logs`).
* Картинки постов отдаются по `/media/<project>/<guid>.png` без авторизации (имена случайные).
  Если это не подходит, закройте `/media` на reverse-proxy.
* Перед выходом в интернет поставьте reverse-proxy с HTTPS и ограничением частоты запросов на `/api/auth/login`.

## Разработка

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg2://vk:vk@localhost:5432/vkreger
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q default,publishing,inbox -l INFO
celery -A app.workers.celery_app beat -l INFO

# тесты (нужна PostgreSQL-база vkreger_test; VK API и OpenAI замоканы)
python -m pytest -q
ruff check app tests

# frontend
cd frontend && npm install && npm run dev   # проксирует /api на BACKEND_INTERNAL_URL (по умолчанию localhost:8000)
```

Новая миграция: `alembic revision --autogenerate -m "..."`.

### Как расширять

* **Другой LLM-провайдер:** реализуйте `LLMProvider` (`app/openai/provider.py`) и выберите его в `get_provider()`.
* **Другой генератор картинок:** реализуйте `ImageProvider` (`app/images/base.py`) и подключите в `app/images/factory.py`.
* **Новый агент или операция:** модуль в `app/openai/agents/`, вызов через `AIService.run()`.
  Учёт стоимости и лимиты работают автоматически.
* **Периодические задачи:** `beat_schedule` в `app/workers/celery_app.py`.
