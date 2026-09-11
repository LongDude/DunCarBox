# AGENT HANDOFF

## Completed

- Финальная интеграция выполнена поверх текущих изменений агентов.
- Default app factory использует DeterministicPackingEngine, версия candidate-packing-v1.
  Произвольные валидные заказы действительно рассчитываются сервером.
- PostgreSQL 17 — единственное серверное хранилище. CRUD, транзакционный seed,
  конкурентные запросы и сохранение после перезапуска проверены.
- Реальный engine → PackingService → API → frontend работает с неизменёнными DTO.
  Инструкции главного плана и альтернатив совпадают с placements.
- React MVP: формы заказа/каталога, 3D, слои, шаги, альтернативы, JSON, печать/PDF.
  Явный автономный demo-режим сохранён для показа без backend.
- Production-образы собраны, PostgreSQL/backend/nginx запущены и healthy.
- README, CONTRACTS, ARCHITECTURE, UX, PACKING_ENGINE и TASKS приведены к итоговому состоянию.

## In progress

Нет незавершённых обязательных работ хакатонного MVP.

## Known issues

- Эвристика не гарантирует оптимум или полноту. Статус impossible означает ноль
  размещённых товаров; точная причина находится в issues.
- Опора проверяется по площади (минимум 80%), без центра масс, нагрузок, хрупкости
  или траектории внесения товара. Это не полная механическая модель.
- Большие разнородные заказы и много типов коробок могут считаться долго.
  Серверный поиск синхронный. Клиент ждёт /pack до 120 секунд; отмена в браузере
  прекращает ожидание, но уже начатый серверный поиск завершается самостоятельно.
- Расчёт не резервирует остатки; история заказов и авторизация не входят в MVP.
- Vite сообщает о размере ленивого Three.js chunk (>500 КБ до gzip, около 240 КБ
  gzip). Это предупреждение, production build успешен.
- pytest выдаёт два deprecation warning стороннего Starlette TestClient;
  все проверки проходят. Frontend без WebGL2 использует проверенный SVG fallback.

## Contracts frozen

- SOURCE OF TRUTH: [CONTRACTS.md](CONTRACTS.md), API v1.
- Доменные и HTTP/TypeScript-поля сохранены; новые relationships/complexity/support
  DTO для MVP не добавлялись. Порог опоры остаётся внутренним EngineOptions.
- Целые мм/г; x=length, y=width, z=height; origin — передний левый нижний угол.
  Three.js mapping: (x,y,z) → (x,z,-y), размеры уже ориентированы движком.
- POST /pack получает snapshot boxes/products/options и ничего не списывает.
  Статусы: success/partial/impossible. Живой ответ не содержит DEMO_STUB.
- prepare=0, place=1..N, close=N+1. Сервис формирует инструкции из placements;
  UI показывает ту же последовательность.
- Offline demo воспроизводит статические JSON и всегда показывает DEMO_STUB.
  Python DemoPackingEngine остаётся явно подключаемым adapter, не default engine.
- PostgreSQL подключается через DUNCARBOX_DATABASE_URL. Compose использует db
  и PGUSER/PGPASSWORD/PGDATABASE; SQLite и автоматического fallback нет.

## Packing agent tasks

Обязательные задачи завершены. Владение: backend/app/packing/**,
backend/tests/packing/**, PACKING_ENGINE.md. Возможное дальнейшее развитие:
детерминированный бюджет поиска, качество эвристик для крупных заказов,
полная опора/ограничения нагрузки по отдельному согласованному контракту.

## Frontend agent tasks

Обязательные задачи завершены. Владение: frontend/** и UX.md.
Дальнейшее развитие: измерения загрузки Three.js, дополнительные виды печати
и история по отдельному контракту. Live E2E находятся в frontend/e2e/live.spec.ts.

## Integration tasks

Обязательная интеграция завершена. При дальнейших изменениях повторять:
backend pytest/Ruff с реальным PostgreSQL, frontend Vitest/build,
Playwright с DUNCARBOX_LIVE_E2E=1 на запущенном API, Docker smoke.
Не возвращать default factory к fixture stub.

## Verification — финальный прогон

- Python 3.12.13, backend pytest: **322 passed**. Включены 241 тест ядра,
  geometry/support/stock/weights, независимая валидация, hash-seed и параллельный
  детерминизм, API/DTO, PostgreSQL, четыре реальные demo-сценария и негативные случаи.
- HTTP-тесты проверяют полное соответствие инструкций размещениям, главный план
  и альтернативы; fixture JSON не используется как ожидаемый реальный packing.
- Frontend Vitest: **71 passed**. Production TypeScript/Vite build успешен
  локально и внутри Docker; зависимости устанавливаются по lock-файлам.
- Playwright на production nginx: **19 passed**. 13 offline/контролируемых
  сценариев плюс 6 live через настоящий API/PostgreSQL: четыре demo, изменение
  количества с 2 на 3, создание/перезагрузка/редактирование/удаление коробки.
  Проверены 3D, слои, шаги, альтернативы, JSON, печать и fallback без WebGL.
- Desktop 1440px и mobile 390px production UI осмотрены; ошибок JS и
  горизонтальной прокрутки страницы нет. Снимки: .cache/mvp-desktop.png,
  .cache/mvp-mobile.png (игнорируются Git).
- docker compose config и production build/up успешны. Все три сервиса healthy.
  Проверка выполнялась в отдельном проекте duncarbox-integration: UI 18080,
  API 18000, PostgreSQL 55433; существующий пользовательский проект не затронут.
- Перезапуск PostgreSQL и backend: созданная запись сохранилась, удалённая
  seed-запись не восстановилась. Тестовые изменения каталога убраны.
- Benchmark --repeat 2 --stress: 10 сценариев, независимая валидация и полное
  совпадение повторов. Это проверка примеров, не SLA для верхней границы API.
- Ruff и git diff --check проходят.

| Demo | Статус | Упаковано | Коробок |
|---|---|---:|---:|
| simple-order | success | 2/2 | 1 |
| multiple-boxes | success | 6/6 | 2 |
| oversized | impossible | 0/1 | 0 |
| stock-shortage | partial | 1/3 | 1 |

## Исправления интеграции и review

- Устранено главное расхождение: готовый engine был недостижим через default API.
- Старые HTTP-ожидания «fixture equality / 503 на изменённый заказ» заменены
  проверками реального расчёта, инвариантов и инструкции для каждого плана.
- Увеличен таймаут только расчёта до 120 секунд; nginx ждёт 125 секунд,
  каталоговые запросы сохраняют 15 секунд. Добавлен регрессионный тест.
- E2E изолирован от оставленного dev-сервера на порту 5173: default test Vite
  использует 5174 и обновляет dependency cache; production URL задаётся явно.
- Проверены границы/повороты/опора, conservation, stock/weights, чистота домена,
  состояние/отмена UI, error envelopes, alternative steps и экспорт.
  Дефектов геометрии в выполненных проверках не обнаружено.
