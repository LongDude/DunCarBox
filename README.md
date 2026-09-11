# DunCarBox

Сервис интеллектуальной упаковки заказов для хакатона: FastAPI, чистые Python domain-модели, PostgreSQL 17 и frontend на React / TypeScript / Vite с пошаговой 3D-инструкцией.

**Frontend MVP и вычислительное ядро реализованы; подключение ядра к API остаётся этапом интеграции.** Default backend пока возвращает фиксированные ответы для четырёх demo-сценариев; произвольные запросы получают HTTP 503. Интерфейс поддерживает каталог коробок, ввод заказа, 3D/слои, пошаговую укладку, альтернативы, диагностику, JSON и печать/PDF. Для презентации доступен автономный демо-режим без backend.

## Быстрый запуск

Нужны Docker и Docker Compose с работающим Docker Engine. Из корня репозитория:

```sh
docker compose up --build
```

- Интерфейс: http://localhost:8080
- Swagger / OpenAPI: http://localhost:8000/docs
- Проверка API: http://localhost:8000/api/v1/health

Для изменения портов скопируйте `.env.example` в `.env` и измените значения перед запуском. По умолчанию Docker публикует порты только на локальном компьютере. PostgreSQL доступен на `127.0.0.1:5432`; база, пользователь и пароль по умолчанию — `duncarbox`. Эти реквизиты предназначены для локальной разработки и демонстрации.

Каталог коробок хранится только в PostgreSQL. Compose ожидает готовности базы перед запуском backend. Данные находятся в volume `postgres_data` и сохраняются после `docker compose down`. `docker compose down -v` удаляет базу. Переменные `POSTGRES_*` создают пользователя и базу при первой инициализации volume; изменение `.env` не меняет пароль уже созданной роли.

## Локальная разработка

Нужны Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24 с npm и работающий PostgreSQL 17. Из корня репозитория можно запустить только базу в Docker:

```sh
docker compose up -d --wait db
```

Затем запустите backend и frontend в двух терминалах. Backend по умолчанию подключается к `postgresql://duncarbox:duncarbox@127.0.0.1:5432/duncarbox`; при другом адресе или реквизитах задайте `DUNCARBOX_DATABASE_URL` в окружении.

Backend — PowerShell, Linux или macOS:

```sh
cd backend
uv sync --frozen --python 3.12
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend — PowerShell:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Frontend — Linux / macOS:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Откройте http://127.0.0.1:5173. Vite передаёт запросы `/api` backend на порту 8000. В PowerShell используется `npm.cmd`, чтобы запуск не зависел от разрешения выполнения `npm.ps1`. Активация виртуального окружения не нужна: `uv run` использует `backend/.venv`.

Для автономной демонстрации запустите только frontend и откройте [демо без сервера](http://127.0.0.1:5173/?mode=demo). Выберите сценарий, нажмите «Загрузить демо-заказ», затем «Рассчитать упаковку». Четыре сценария включают полную упаковку, несколько коробок, слишком крупный товар и нехватку коробок. Локальный каталог сохраняется в браузере; демо воспроизводит готовые fixtures и не рассчитывает изменённые заказы. Подробности: [UX.md](docs/UX.md).

Локальные параметры backend задаются переменными окружения; примеры приведены в `.env.example`. Docker Compose читает `.env` автоматически, локальный backend — переменные своей оболочки. `DUNCARBOX_DATABASE_URL` принимает PostgreSQL URI. Для пароля со специальными символами можно использовать URI только с адресом (`postgresql://127.0.0.1:5432`) и отдельно экспортировать `PGUSER`, `PGPASSWORD`, `PGDATABASE`; Compose уже использует такой способ.

## Проверки

Для полного набора backend-тестов нужен работающий PostgreSQL. По умолчанию тесты используют локальную demo-базу выше; `DUNCARBOX_TEST_DATABASE_URL` позволяет выбрать другую базу. Тесты создают собственные временные схемы и удаляют только их; тестов с подменой хранилища нет. Пользователь тестовой базы должен иметь право `CREATE` на базу.

```sh
cd backend
uv run pytest
uv run ruff check app tests
```

Для нестандартного подключения задайте переменную перед `pytest`: в PowerShell — `$env:DUNCARBOX_TEST_DATABASE_URL = 'postgresql://127.0.0.1:5432/test_database'`, в Linux/macOS — `export DUNCARBOX_TEST_DATABASE_URL='postgresql://127.0.0.1:5432/test_database'`. Пользователь и пароль могут передаваться через `PGUSER` и `PGPASSWORD`.

```sh
cd frontend
npm test
npm run build
npm run test:e2e
```

В PowerShell используйте `npm.cmd run build`. Из корня репозитория `docker compose config --quiet` проверяет конфигурацию контейнеров без их запуска.

Для E2E используется установленный Chrome на Windows; на другой машине установите Chromium командой `npx playwright install chromium` либо укажите путь через `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. Тесты запускают локальный Vite, проверяют автономный demo и HTTP-клиент с контролируемыми API-ответами; PostgreSQL для них не требуется.

## Структура и передача работы

| Путь | Содержимое |
| --- | --- |
| `backend/app/domain/` | Модели, независимые от HTTP и хранения |
| `backend/app/api/`, `schemas/`, `services/` | REST API, валидация, сценарии приложения |
| `backend/app/packing/` | Точка подключения будущего ядра |
| `backend/app/storage/` | PostgreSQL-каталог коробок через psycopg 3 |
| `frontend/` | Формы, пошаговый 3D-интерфейс, типизированный API/demo и тесты |
| `demo/` | Четыре фиксированных запроса и ответа для UI |
| `docs/` | Архитектура, контракты и задания агентам |

Сначала прочитайте [контракты](docs/CONTRACTS.md) и [передачу работы агентам](docs/AGENT_HANDOFF.md). Устройство компонентов описано в [архитектуре](docs/ARCHITECTURE.md); следующие задачи — в [TASKS.md](docs/TASKS.md), [PACKING_ENGINE.md](docs/PACKING_ENGINE.md) и [UX.md](docs/UX.md).

Все размеры — в миллиметрах, масса — в граммах. Координаты: `x` — длина, `y` — ширина, `z` — высота. Запрос упаковки использует переданный снимок остатков и не изменяет каталог коробок.
