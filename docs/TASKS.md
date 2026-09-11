# Задачи и границы этапов

## Foundation (этот этап)

- [x] Monorepo, Python 3.12+, React / TypeScript / Vite.
- [x] Чистые доменные модели и интерфейс PackingEngine.
- [x] Контракт API v1, мм/г, координаты, ориентации, ошибки и детерминизм.
- [x] FastAPI, строгая валидация, PostgreSQL CRUD каталога через psycopg 3.
- [x] Четыре пары demo-request/response и явный fixture stub.
- [x] Генерация русских инструкций из placements.
- [x] Каркас клиента, API-клиент и согласованные TypeScript-типы.
- [x] Dockerfiles, Compose, env-example и README.
- [x] Backend API/schema/fixture tests.
- [x] API/storage tests на реальном PostgreSQL: 72 passed; HTTP CRUD и demo smoke.
- [ ] Проверить сборку и запуск Compose при доступном Docker daemon (config валиден).

## Следующий этап — Packing Engine Engineer

- [ ] Реальная детерминированная эвристика и documented tie-break.
- [ ] Геометрия/повороты/вес/остатки для произвольных валидных заказов.
- [ ] Объяснения, частичный результат, альтернативы, meaningful metrics.
- [ ] Собственные tests/packing и обновление PACKING_ENGINE.md.

## Следующий этап — Frontend / 3D / UX Engineer

- [ ] Формы заказа и управление каталогом коробок.
- [ ] 3D-визуализация фактических placements.
- [ ] Переключение коробок, шагов и альтернатив; выделение текущего товара.
- [ ] Полные loading/error/empty/partial/impossible состояния.
- [ ] Адаптивность и UX-проверки; обновление UX.md.

## Финальная интеграция — отдельная команда пользователя

- [ ] Прочитать текущие HANDOFF и CONTRACTS; не создавать проект заново.
- [ ] Подключить ядро вместо stub, согласовать клиент и сервер.
- [ ] Проверить реальные demo-заказы и негативные случаи, determinism и инструкции.
- [ ] Запустить backend/frontend проверки и Docker при доступном daemon.
- [ ] Финальный review и обновление README/HANDOFF.
