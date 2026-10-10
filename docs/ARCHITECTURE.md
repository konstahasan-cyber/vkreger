# VKreger — архитектура

Платформа для создания, оформления и ведения сообществ ВКонтакте с помощью AI (OpenAI).
Цель — управлять десятками сообществ из одной панели. Генерацию и оптимизацию контента
берёт на себя AI.

## 1. Принципы

* Работаем только через официальный VK API (`api.vk.com/method/*`, версия задаётся в
  `VK_API_VERSION`) и официальные механизмы событий (Callback API, Bots Long Poll API).
* Нет обхода CAPTCHA, антибот-защиты и ограничений VK, нет подмены fingerprint и
  авто-регистрации. Пользователь сам импортирует **свои** токены. Если VK возвращает
  `Captcha needed` (код 14) или `Flood control` (код 9), задача останавливается и пишет
  ошибку в журнал. Повторов «в обход» нет.
* Proxy — это просто сетевая конфигурация конкретного аккаунта (один proxy на аккаунт).
* Секреты: `.env` → environment. Токены VK, community-токены и пароли proxy лежат в БД
  в зашифрованном виде (Fernet / `MultiFernet`, поддерживается ротация ключей).
* AI-провайдер, модели, цены и лимиты задаются в конфиге (env + переопределения в БД через
  страницу «AI Settings»), а не в коде.

## 2. Компоненты

```
┌─────────────┐   REST/JWT   ┌──────────────────────┐        ┌──────────────┐
│ Next.js     │ ───────────▶ │ FastAPI (backend)    │ ─────▶ │ PostgreSQL   │
│ admin panel │              │  app/api/*           │        └──────────────┘
└─────────────┘              │  services / repos    │        ┌──────────────┐
                             └─────────┬────────────┘ ─────▶ │ Redis        │
     VK Callback API ─────────────────▶│ /api/vk/callback    │ broker/cache │
                                       │                     └──────┬───────┘
                             ┌─────────▼────────────┐               │
                             │ Celery worker + beat │ ◀─────────────┘
                             │  publish / analytics │──▶ VK API (через proxy аккаунта)
                             │  proxies / inbox     │──▶ OpenAI API (Responses, Images,
                             │  autopilot / analyst │                Embeddings)
                             └──────────────────────┘
```

### Структура backend

```
backend/app/
  main.py            — фабрика FastAPI-приложения
  core/              — config, security (JWT, пароли), crypto (шифрование), rbac, logging (редакция секретов)
  db/                — engine, session, Base, EncryptedText
  models/            — SQLAlchemy-модели
  schemas/           — Pydantic-схемы API
  repositories/      — доступ к данным
  services/          — бизнес-логика: аккаунты, проекты, сообщества, посты, inbox, лиды, дашборд, аудит, cost guard
  vk/                — VK API клиент, ошибки, загрузка фото, обработка Callback/Long Poll
  proxy/             — парсер форматов, проверка, пул/автозамена
  openai/            — LLM provider interface, OpenAI provider, pricing, учёт расходов, контекст-билдер, агенты
  images/            — Image Provider Interface (OpenAI Images / disabled / ...)
  content/           — пайплайн генерации постов, анти-повторы (semantic + lexical), планировщик слотов
  analytics/         — сбор статистики VK и агрегаты для ANALYST
  workers/           — Celery app, beat-расписание, задачи
  api/               — роутеры FastAPI
```

## 3. AI-агенты и экономия токенов

| Роль | Операция (`operation`) | Когда | Объединение |
|---|---|---|---|
| STRATEGIST | `project_setup` | один раз при создании проекта | анализ бизнеса + ЦА + названия + описание + статус + рубрики + стратегия + оформление — **один вызов** |
| STRATEGIST | `content_plan` | при пустом плане / раз в период | — |
| COPYWRITER + EDITOR + IMAGE_PROMPT_AGENT | `post_compose` | каждый пост | **один вызов**: текст, заголовок, CTA, хештеги, промпт картинки, self-review |
| EDITOR | `post_edit` | опционально (`AI_SEPARATE_EDITOR_PASS`) | плюс бесплатный локальный фильтр AI-штампов |
| ANALYST | `analytics_review` | по расписанию, не чаще `ANALYST_MIN_INTERVAL_DAYS` и не раньше `ANALYST_MIN_NEW_POSTS` новых постов | — |
| COMMUNITY_MANAGER | `inbox_triage` | входящее сообщение/комментарий | классификация + черновик ответа + извлечение полей лида — **один вызов** |

Каждому агенту передаётся только тот контекст, который ему нужен (`app/openai/context.py`):

* `project_context` — сжатое резюме бизнеса, создаётся один раз при `project_setup` и
  сохраняется в `projects.context_summary`;
* `brand_context` — название, ToV, стиль CTA;
* `content_rules` — рубрики, запреты, длина;
* `recent_posts_summary` — последние N тем/заголовков/CTA одной строкой каждый
  (без полных текстов);
* `analytics_summary` — агрегаты (по категориям, по часам, средний engagement).

Статическая часть (instructions) стоит первой, а `prompt_cache_key=project:{id}` позволяет
пользоваться prompt caching OpenAI.

### Сеть групп (много групп на одну тему)

* `projects.network` объединяет проекты групп одной тематики. Каждая группа — отдельный проект
  со своей очередью, расписанием и входящими.
* Быстрый ввод (`POST /networks/bulk`): строки «ID ключ», «ключ» или «ссылка; ключ». Группа
  определяется через `groups.getById` по ключу сообщества. Ключ хранится зашифрованным, а в
  ответах API маскируется.
* STRATEGIST вызывается один раз на сеть. Остальные группы получают копию анализа, рубрик и
  стратегии (`network_service.copy_strategy`).
* Каждая группа получает свой «голос» (`app/content/personas.py`): кто пишет, структура поста,
  первая строка, длина и эмодзи. Блок `author_voice` передаётся в контент-план и в генерацию поста.
* Контент-план видит темы, уже занятые другими группами (`network_taken`), а генерация видит их
  последние посты (`network_posts`). Планы составляются по очереди, посты пишутся параллельно.
* Проверка повторов (`check_uniqueness(sibling_ids=…)`) сравнивает пост с постами других групп
  сети по заголовку, первой строке и эмбеддингу. Похожий пост переписывается, а если все попытки
  остались похожими, сохраняется наименее похожий вариант.
* `GET /networks/similar` и задача `network_dedupe` находят похожие посты в уже написанном и
  переписывают более новый неопубликованный пост (картинка и время остаются прежними).
* Время публикации групп сдвигается на +4 минуты на каждую группу.

## 4. Схема БД (основные таблицы)

| Таблица | Ключевые поля |
|---|---|
| `users` | email, password_hash, role (owner/admin/operator/viewer), is_active |
| `audit_logs` | user_id, action, entity_type, entity_id, details JSON, ip, created_at |
| `system_logs` | level, source, message, context JSON, project_id, created_at |
| `proxies` | scheme, host, port, username, password🔒, status (unknown/alive/dead), external_ip, country, latency_ms, last_checked_at, last_error, fail_count |
| `vk_accounts` | name, vk_user_id, access_token🔒, status (new/active/invalid/error/disabled), last_checked_at, proxy_id (unique, nullable), auto_replace_proxy, last_error, info JSON |
| `communities` | vk_group_id, name, screen_name, account_id, project_id, community_token🔒, is_admin, members_count, event_mode (none/callback/longpoll), callback_secret🔒, confirmation_code, callback_server_id, longpoll_ts, settings JSON |
| `projects` | name, network, business_name, theme, niche, city, target_audience, product_description, advantages, website, contacts, goal, posts_per_day, posts_per_week, tone, custom_tone_prompt, vk_account_id, status, setup_proposal JSON, context_summary, brand JSON, content_rules JSON, timezone, posting_times JSON, autopilot, auto_approve, auto_reply mode, auto_reply_types, image settings |
| `rubrics` | project_id, code, name, description, weight, is_active |
| `strategies` | project_id, version, is_active, data JSON, source (setup/analyst/manual), reasoning |
| `content_plan_items` | project_id, rubric_code, topic, angle, planned_for, status (planned/used/skipped), post_id |
| `posts` | project_id, community_id, title, text, attachments JSON, category, scheduled_at, published_at, status, vk_post_id, guid, attempts, last_error, generation_metadata JSON, analytics JSON, topic, cta, hashtags JSON, image_prompt, image_format, image_path, embedding JSON, is_pinned |
| `post_stat_snapshots` | post_id, views, likes, comments, reposts, clicks, reach, collected_at |
| `inbox_items` | project_id, community_id, kind (comment/message), vk ids, from_id, text, classification, confidence, suggested_reply, reply_text, reply_status, handled_by, sent_at |
| `leads` | project_id, inbox_item_id, vk_user_id, name, contact, need, status, notes |
| `notifications` | kind, title, body, project_id, is_read |
| `ai_usage` | model, operation, agent, input_tokens, output_tokens, cached_tokens, images, estimated_cost, project_id, success, created_at |
| `app_settings` | key, value JSON — переопределения конфигурации из панели |
| `jobs` | type, status, project_id, progress, result JSON, error — длинные фоновые операции для UI |

🔒 — колонка хранится в зашифрованном виде (`EncryptedText`).

## 5. Публикация без дубликатов

1. Beat раз в минуту вызывает `dispatch_due_posts`: атомарный
   `UPDATE posts SET status='publishing' WHERE status='scheduled' AND scheduled_at<=now()`
   с `FOR UPDATE SKIP LOCKED`, затем отдельная задача на каждый пост.
2. `publish_post`: если `vk_post_id` уже есть, пост просто помечается `published`.
   Иначе вызывается `wall.post` с `guid=<post.guid>`: VK сам не создаст вторую запись
   с тем же guid.
3. Ошибка → `attempts += 1`, `last_error` и запись в `system_logs`. Retryable-ошибки
   (сеть, 5xx, 6/10) дают экспоненциальный backoff и возврат в `scheduled`. При
   `attempts >= PUBLISH_MAX_ATTEMPTS` или фатальной ошибке (5, 15, 214, 14 captcha) пост
   переходит в `failed`.
4. Посты, застрявшие в `publishing`, проверяются через `wall.get`: ищем текст среди
   последних записей. Нашли — фиксируем `vk_post_id`, не нашли — возвращаем в очередь.

## 6. Лимиты расходов

`CostGuard` перед каждым AI-вызовом сравнивает сумму `ai_usage.estimated_cost` за сегодня
(глобально и по проекту) с `MAX_AI_COST_PER_DAY` и `MAX_AI_COST_PER_PROJECT_DAY`.
Автоматические задачи (autopilot, analyst, auto-reply) при превышении лимита
останавливаются и пишут предупреждение. Ручные операции тоже блокируются, но
администратор может явно передать `force=true`.

## 7. RBAC

Роли `owner > admin > operator > viewer`. Права описаны в `app/core/rbac.py`
(`Permission.*`), а эндпоинты защищены зависимостью `require(Permission.X)`.
Действия, которые что-то меняют, пишутся в `audit_logs`.

## 8. TODO / этапы

MVP (реализовано):
- [x] Авторизация в панели (JWT), bootstrap администратора, RBAC-каркас, аудит
- [x] PostgreSQL + Alembic миграции
- [x] VK-аккаунты: добавить/удалить/проверить/обновить/получить сообщества
- [x] Proxy Manager: массовый импорт всех форматов, проверка (IP, страна, latency), привязка, автозамена
- [x] Проекты: форма, выбор аккаунта
- [x] OpenAI: Responses API, structured outputs, учёт токенов и стоимости, лимиты
- [x] Стратегия (STRATEGIST), контент-план, генерация поста (COPYWRITER+EDITOR+IMAGE_PROMPT)
- [x] Анти-повторы: embeddings + лексическое сходство заголовков/CTA
- [x] Подключение/создание сообщества (preview → «Создать»), настройка, закреплённый пост
- [x] Очередь публикаций, планировщик, ретраи, защита от дублей
- [x] Журнал ошибок, системные логи
- [x] Базовая аналитика (wall.getById + stats.getPostReach)

Расширения (реализовано):
- [x] Изображения: Image Provider Interface, OpenAI Images, загрузка в VK
- [x] Callback API + Long Poll, классификация входящих, AUTO_REPLY OFF/APPROVAL/AUTO, лиды, уведомления
- [x] ANALYST: периодическая ревизия стратегии
- [x] Dashboard расходов OpenAI (сегодня / 7 / 30 дней / проекты / операции)

Дальше:
- [ ] Генерация аватара/обложки сообщества через Image Provider (интерфейс готов: `vk/uploads.py`)
- [ ] VK ID OAuth flow (сейчас токен импортируется вручную)
- [ ] pgvector вместо JSON-эмбеддингов, когда постов станет > 10k на проект
- [ ] Мульти-тенантность (organization_id) поверх RBAC
- [ ] Уведомления оператору в Telegram/email (сейчас: панель + `OPERATOR_WEBHOOK_URL`)
