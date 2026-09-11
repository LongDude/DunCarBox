# AGENT HANDOFF

## Completed

- Foundation monorepo, API v1 и доменные dataclasses.
- PostgreSQL-каталог с CRUD и однократным seed; расчёт не списывает остатки.
- Четыре проверяемых demo-сценария и детерминированный fixture stub.
- Сервис генерации русских инструкций из placements.
- React/TypeScript/Vite skeleton и типизированный клиент API.
- Docker/Compose/env/README, архитектура и задания следующим агентам.

## In progress

- Нет незавершённых изменений текущего этапа. Переход на PostgreSQL завершён;
  реализации packing engine и полноценного 3D/UX ожидают следующего этапа.

## Known issues

- Настоящий packing engine ещё не реализован по границе текущего задания.
  Произвольный валидный запрос получает 503 ENGINE_NOT_IMPLEMENTED.
- Полноценный 3D/UX, формы, альтернативные планы и алгоритм — следующий этап.
- Docker daemon в текущем окружении недоступен; Compose config можно проверить,
  сборку образов и запуск контейнеров необходимо проверить при работающем Docker.
- Установка backend использует Python 3.12.13 в локальном `.cache/python`;
  системный Python здесь 3.11. Пользователю достаточно `uv sync --python 3.12`.
- pytest выдаёт два deprecation warning из стороннего Starlette TestClient
  (httpx и AnyIO BlockingPortal); тесты проходят, runtime API это не блокирует.

## Contracts frozen

- Источник истины: [CONTRACTS.md](CONTRACTS.md), версия v1.
- Размеры/позиции: целые мм, вес: целые г, origin передний левый нижний угол;
  x=length, y=width, z=height. Ориентация — permutation string LWH и ещё 5 вариантов.
- Domain: `backend/app/domain/models.py`, `interfaces.py`; HTTP: `schemas/packing.py`;
  TypeScript: `frontend/src/types/packing.ts`.
- POST /pack получает snapshot boxes/products/options; статусы
  success/partial/impossible. PackingService добавляет инструкции к основному плану
  и альтернативам. Шаги prepare=0, place=1..N, close=N+1.
- Stub использует статические fixtures, его marker DEMO_STUB нельзя скрывать.
- Единственное хранилище — PostgreSQL через psycopg 3. Подключение задаётся
  `DUNCARBOX_DATABASE_URL`. PostgreSQL обязателен и для API-тестов; отдельная
  случайная схема на тест не затрагивает существующий каталог. Автоматического
  переключения на другую базу нет. HTTP-контракт при замене хранилища не изменён.

## Packing agent tasks

- Владеет `backend/app/packing/**`, `backend/tests/packing/**`, `PACKING_ENGINE.md`.
- Реализовать `pack(PackingRequest) -> PackingResult`, без HTTP/ORM/GUI.
- Обеспечить геометрию, ориентации, вес, остатки, детерминизм, причины и метрики.
- Общие модели и API не менять без интегратора. См. PACKING_ENGINE.md и TASKS.md.

## Frontend agent tasks

- Владеет `frontend/**` и `UX.md`; Dockerfile/nginx уже подготовлены интегратором.
- Развить skeleton в формы каталога/заказа и пошаговый 3D-интерфейс.
- Использовать типы и fetch-клиент; Three.js mapping `(x,y,z) → (x,z,-y)`.
- Показывать инструкции сервера; синхронизировать видимые placements по step.
- См. UX.md и TASKS.md; не считать demo-stub полноценным расчётом.

## Integration tasks

- После отдельной команды пользователя прочитать актуальный репозиторий и этот файл.
- Подключить движок в app factory, проверить frontend↔API и реальные сценарии.
- Повторить тесты, frontend build и Docker smoke; review геометрии и инструкций.
- Сохранять working demo, обновить README и этот handoff.

## Verification

- Python 3.12.13, `uv sync --frozen --offline`: зависимости воспроизводимо
  устанавливаются из lock-файла. `pytest -q`: **72 passed на PostgreSQL 17.11**.
- PostgreSQL проверен реальным локальным сервером на 127.0.0.1:55432, без
  подмены хранилища. Тесты используют DUNCARBOX_TEST_DATABASE_URL и отдельные
  временные схемы. Повторный прогон с options/statement_timeout и символом `+`
  в URI также успешен. Создание схем, seed и CRUD работают транзакционно.
- Дополнительные PostgreSQL-тесты: 8 одновременных инициализаций, откат неудачного
  seed вместе с DDL/маркером, работа после конфликта, сортировка независимо от
  локали базы, отказ при недоступном PostgreSQL без другого хранилища.
- `ruff check app tests` и `git diff --check`: успешно.
- Backend реально запускался Uvicorn на 127.0.0.1:8000; health и четыре сценария
  по HTTP: success (1 коробка), success (2), impossible (0), partial (1).
- HTTP CRUD проверен с PostgreSQL, сохранённая через API запись подтверждена
  прямым SELECT. Все четыре demo-запроса прошли с новым подключением.
- Tests проверяют входные ограничения, ошибки, CRUD/перезапуск, конкурентные
  дубликаты, детерминизм, полное совпадение API с fixture JSON, геометрию,
  ориентации, вес, остатки, метрики и согласованность инструкций с placements.
- Независимый review foundation: проверены конкурентный seed, отсутствие повторного
  заполнения удалённого каталога, 405/Allow и 500 с CORS и безопасной оболочкой.
- Frontend-проверки предыдущего foundation-этапа (клиент в переходе на PostgreSQL
  не менялся): `npm run build` — strict TypeScript + Vite production build успешен.
  `npm install`: согласованы peer-зависимости React 19.2 и React Three Fiber;
  package-lock.json записан. npm audit при установке: 0 vulnerabilities.
- Vite стартовал на 127.0.0.1:5173; index, TSX и /api proxy прошли HTTP smoke.
- Headless Chrome: нажаты все четыре сценария и кнопка получения плана;
  ожидаемые статусы и инструкции отображаются, ошибок JS нет. Проверены desktop
  и mobile (390px), горизонтальной прокрутки нет. Временные скриншоты — `.cache/`.
- `docker --config .docker-local compose config --quiet`: успешно.
  Docker build/up не запускались: отсутствует pipe Docker Engine.
