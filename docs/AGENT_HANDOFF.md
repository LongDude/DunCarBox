# AGENT HANDOFF

## Completed

- Foundation monorepo, API v1 и доменные dataclasses.
- PostgreSQL-каталог с CRUD и однократным seed; расчёт не списывает остатки.
- Четыре проверяемых demo-сценария и детерминированный fixture stub.
- Сервис генерации русских инструкций из placements.
- React/TypeScript/Vite frontend MVP: формы каталога/заказа, автономные demo,
  типизированный API, пошаговые 3D/слои, альтернативы и печать/JSON.
- Docker/Compose/env/README, архитектура и задания следующим агентам.
- Ядро `DeterministicPackingEngine` (`candidate-packing-v1`) реализовано в
  `backend/app/packing/`: целочисленная геометрия, уникальные повороты, опора,
  до 12 deterministic starts, выбор нескольких коробок с учётом stock, scoring,
  причины частичной упаковки, distinct alternatives и независимый валидатор.
- Внутренние helpers relationships/complexity и EngineOptions, pytest suite
  `backend/tests/packing/`, benchmark `python -m app.packing.benchmark`.
  Подробности и предложения по контракту: [PACKING_ENGINE.md](PACKING_ENGINE.md).

## In progress

- Реализация packing engine и frontend MVP завершена. Подключение движка к
  default app factory и проверка общей интеграции остаются за интегратором.

## Known issues

- Default app factory пока выбирает fixture stub, поэтому произвольный HTTP
  запрос всё ещё получает 503 ENGINE_NOT_IMPLEMENTED. Реальное ядро готово;
  интегратору передать `engine=DeterministicPackingEngine()` в create_app.
- Frontend отображает формы, 3D/слои и полноценные альтернативные планы по
  существующим DTO. Сквозная проверка с реальным движком требует его подключения
  к app factory; текущий серверный режим продолжает работать с fixture stub.
- Эвристика не доказывает оптимальность/полноту; большие разнородные заказы при
  большом числе типов коробок могут быть дорогими. Опора по площади не моделирует
  центр масс, нагрузку на товар или траекторию загрузки.
- В API v1 отсутствует настройка опоры и metadata relationships/complexity.
  Контракт не изменён: пока использовать EngineOptions и backend helpers;
  минимальные предложения перечислены в PACKING_ENGINE.md.
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
- Выполнено: `pack(PackingRequest) -> PackingResult`, без HTTP/ORM/GUI.
- Выполнено: геометрия, ориентации, вес, stock, опора, детерминизм, причины и метрики.
- Defaults EngineOptions: support=4/5, max_candidate_points=128, max_strategies=12,
  max_fill_passes=3, max_alternatives=3. Нестандартные значения отражаются в
  algorithm_version. HTTP PackingOptions по-прежнему содержит только alternatives.
- Главный score: unpacked count, отрицательный packed volume, box count,
  empty volume, complexity, stock tie-break, signature. Альтернативы той же
  полноты сортируются по контрактному порядку и не повторяют одинаковую геометрию.
- Инструкции ядра пустые по контракту; placements пронумерованы снизу вверх.
  PackingService проверен с реальным ядром, включая совпадение инструкций/DTO.
- Общие модели и API не менять без интегратора. См. PACKING_ENGINE.md и TASKS.md.

## Frontend agent tasks

- Владеет `frontend/**` и `UX.md`; Dockerfile/nginx уже подготовлены интегратором.
- Выполнено: CRUD каталога, таблица товаров с добавлением/копированием/удалением,
  контрактная валидация, расчёт с loading/отменой/ошибками и предупреждением об
  устаревшем результате. Снимок сценария отделён от каталога коробок.
- Выполнено: выбор коробок/альтернатив, общий 3D mapping `(x,y,z) → (x,z,-y)`,
  нормализация, подготовка/укладка/закрытие, подсветка, автопоказ и вид по слоям.
- Выполнено: серверные инструкции доступны рядом с геометрическими пояснениями;
  печать всех коробок выбранного плана, JSON с исходным ответом и выбранным планом.
- Выполнено: единый live/demo адаптер. По умолчанию API; автономный режим явно
  включается через UI, `?mode=demo` или `VITE_DATA_SOURCE=demo`.
- См. [UX.md](UX.md). Demo-stub остаётся помеченным воспроизведением fixtures;
  клиент не рассчитывает произвольную упаковку и не меняет backend API.

## Integration tasks

- После отдельной команды пользователя прочитать актуальный репозиторий и этот файл.
- Подключить движок в app factory, проверить frontend↔API и реальные сценарии.
- Использовать `from app.packing import DeterministicPackingEngine, EngineOptions`.
  Fixture stub и demo JSON сохранены; тесты будущего HTTP-режима не должны требовать
  побайтного совпадения реальных размещений с authored fixtures.
- Согласовать предложения PACKING_ENGINE.md: HTTP min_support_ratio, уточнение
  описания опоры в CONTRACTS, необязательные relationships/complexity DTO.
  Статус impossible сохранять; эвристическую неудачу объяснять через issues.
- Повторить тесты, frontend build и Docker smoke; review геометрии и инструкций.
- Сохранять working demo, обновить README и этот handoff.

## Verification

### Frontend MVP, 2026-09-11

- `npm run dev`, `npm run test`, `npm run build`, `npm run test:e2e` запускаются
  из `frontend/` (в PowerShell доступен `npm.cmd`). Источник данных по умолчанию —
  API; для демонстрации без backend открыть `/?mode=demo`.
- `npm test`: **70 passed**, 6 файлов. Проверены контрактные ограничения,
  CRUD/изоляция snapshots, точные fixture-ответы и options, отмена, сетевые/HTTP/DTO
  ошибки, оси/центры/нормализация, шаги/слои/framing, API→UI, эвристические причины,
  ориентация, достоверность пространственных подсказок и экспорт альтернатив.
- `npm run test:e2e`: **13 passed** в установленном Chrome с WebGL2/SwiftShader.
  Проверены настоящий Canvas, подготовка/шаги/закрытие, смена коробок и альтернатив,
  JSON download, печать всех коробок, CRUD и сохранение каталога, нулевые остатки,
  добавление/копирование строк, дробные размеры, все четыре demo-сценария,
  HTTP 422 и повторная отправка, восстановление после сбоя загрузки сценария,
  устаревший план и корректность сравнения названий с пробелами, SVG fallback
  с клавиатурой и отсутствие горизонтальной прокрутки страницы на ширине 820px.
  HTTP-кейсы используют контролируемые ответы Playwright, не реальный PostgreSQL.
- `npm run build`: strict TypeScript и Vite production build успешны на Node
  22.22.0 / npm 11.6.2. Главный JS — около 82,5 КБ gzip; лениво загружаемый 3D
  chunk — около 240,4 КБ gzip. Vite предупреждает о размере Three.js chunk >500 КБ
  до gzip; загрузка 3D отделена от форм, сборка завершается успешно.
- Визуально проверены desktop 1440px и mobile 390px; ошибок JavaScript нет,
  горизонтальной прокрутки страницы на 390px нет. Временные снимки находятся в
  игнорируемой `frontend/.cache/`. Vite оставлен на `127.0.0.1:5173`.
- `git diff --check` успешен. Windows sandbox блокировал чтение родительского
  каталога esbuild; сборка, Vitest и headless Chrome выполнены после разрешённого
  запуска вне sandbox. Backend/Compose в этом этапе не запускались и не менялись.

### Frontend implementation and integration notes

- Основные файлы: `src/pages/PackingApp.tsx` управляет черновиком и снимком расчёта;
  `src/features/catalog/` и `order/` — формы; `features/packing/` — результат,
  подсказки, статусы, экспорт; `src/three/` — преобразования, 3D и слои;
  `src/api/` — общий источник и проверки границ. Типы остаются в `src/types/packing.ts`.
- Снимок расчёта не связан с изменяемым каталогом. В API-режиме каталог остаётся
  в PostgreSQL, автономная демо-копия хранится только в браузере под ключом
  `duncarbox.demo.catalog.v1`. При недоступном localStorage сохраняется работа
  в памяти текущего сеанса. Загрузка сценария не перезаписывает каталог.
- Канонические `demo/*.json` скопированы в
  `frontend/src/features/demo/fixture-data/` для изолированной frontend Docker
  сборки. Обновление из корня: `Copy-Item demo/*.json frontend/src/features/demo/fixture-data/`.
  Parity-тест проверяет все JSON побайтно; пропускается только без корневого demo/.
- Изменения товаров, выбранного snapshot/options или номера делают старый результат
  устаревшим. Черновик и история не сохраняются на сервере; смена источника
  создаёт новую рабочую область. Серверный ответ сохраняется вместе с исходным
  запросом; JSON дополнительно содержит выбранный альтернативный план.
- Шаги сервера сохраняются: prepare=0, place=1..N, close=N+1. UI добавляет
  геометрическое пояснение направления сторон, углов, расстояний и касающегося
  соседа; исходный серверный текст доступен в details и печатной инструкции.
  Новые relationships/complexity DTO не требуются и не имитируются.
- Общий scale равен `6 / max(1, length, width, height)`. Уже ориентированные размеры
  используются один раз, origin и mapping `(x,y,z) → (x,z,-y)` общие для коробки
  и товаров. Слои группируются по высоте основания, без arbitrary slicing.
  При недоступном WebGL2 доступен SVG-вид сверху и все инструкции.
- Общий fill_ratio берётся из API как взвешенный по объёму коэффициент. Вес без тары,
  количество операций включает подготовку/закрытие. Показываются до трёх
  альтернатив в порядке API. Печать содержит все коробки выбранного плана,
  содержимое, метрики, полные шаги и неупакованные позиции с причинами.
- Оставшаяся интеграция: подключить `DeterministicPackingEngine` к app factory,
  повторить реальные frontend↔API заказы и HTTP CRUD с PostgreSQL. Factory, API,
  backend и инфраструктура этим frontend-этапом не изменены. Текущий stub по-прежнему
  отвечает 503 на произвольные валидные заказы; локальный demo действует так же
  и никогда не выдаёт новые рассчитанные placements.
- Известные границы UX: при блокировке браузерного хранилища локальный каталог
  не переживёт перезагрузку; геометрия не моделирует физическую траекторию укладки,
  нагрузку на товары или дополнительные отношения опоры. Проверка общей системы
  с реальным движком и production Docker требует отдельного интеграционного прогона.
  Полный workflow и доступные режимы описаны в [UX.md](UX.md).

### Packing engine, 2026-09-11

- Текущее окружение Windows имеет Python 3.11.0; Python 3.12 и `.venv` из
  предыдущего этапа здесь отсутствуют. Код совместим с 3.11 и не добавляет
  runtime-зависимостей. Повторный запуск на целевом Python 3.12 — у интегратора.
- Из backend: `python -m pytest tests/packing tests/test_demo_fixtures.py -q`:
  **262 passed** (241 тест ядра и 21 существующий fixture-тест), около 0.4 с.
  Проверены отдельные границы/AABB/опора union, пороги веса, повороты, stock,
  реальные demo-запросы, count/volume/box scoring, альтернативы и configurable support.
- Дополнительно в этом suite: 48 смешанных заказов с фиксированными seed,
  voxel oracle для геометрии, support dependencies, параллельные вызовы,
  изоляция мутаций и полное совпадение JSON между разными PYTHONHASHSEED.
- `ruff check backend/app backend/tests`, форматирование новых модулей/тестов
  и `git diff --check` успешны. Ruff установлен только в игнорируемый
  `.cache/packing-tools`; зависимости проекта и lock-файл не менялись.
- `python -m app.packing.benchmark --repeat 2 --stress`: все 10 сценариев
  проходят независимую валидацию и полное сравнение повторных результатов.
  Медианы на этой машине: 24 mixed — 76 мс (24/24, одна коробка, 79.17%);
  64 cubes — 29 мс (64/64, одна, 100%); 216 cubes — 469 мс (216/216, одна, 100%);
  120 mixed — 1840 мс (120/120, две, 29.80%). Это примеры, не SLA.
- Существующие HTTP/schema tests пытались запуститься, но 27 проверок не прошли
  setup из-за отсутствующего PostgreSQL (connection timeout). HTTP/storage suite
  целиком не подтверждён в этом окружении; база не подменялась. Ядро, доменные
  DTO и PackingService проверены без базы. Factory/API/storage/frontend не менялись.

### Foundation (исторические проверки предыдущего окружения)

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
