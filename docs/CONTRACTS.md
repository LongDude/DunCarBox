# DunCarBox — контракт v1 (SOURCE OF TRUTH)

Зафиксирован для интегрированного MVP. Изменения согласует интегратор. Python-модели:
`backend/app/domain/models.py`; HTTP-валидация: `backend/app/schemas/packing.py`.
Доменные модели — стандартные dataclasses, без FastAPI, Pydantic, ORM и UI.
JSON использует snake_case. Неизвестные поля входа запрещены.

## Единицы и координаты

- Все размеры и координаты — **целые миллиметры**, вес — **целые граммы**, объём — мм³.
- Внутренние размеры коробки: x = length, y = width/depth, z = height.
- Начало координат — передний левый нижний внутренний угол. x вправо, y вглубь, z вверх.
- `position` — минимальный угол товара, не центр. Границы товара: `[x,x+length]` и аналогично.
- Касание граней разрешено; положительный объём пересечения запрещён.
- Для Three.js с осью Y вверх отображение точки `(x,y,z)` → `(x,z,-y)`;
  центр mesh рассчитывается после прибавления половины ориентированных размеров.
- `orientation` — одна из `LWH,LHW,WLH,WHL,HLW,HWL`: исходные оси товара,
  назначенные осям x,y,z коробки в этом порядке. Например `WLH` даёт
  `dimensions={length:product.width,width:product.length,height:product.height}`.
- Если `allow_rotation=false`, допустима только `LWH`. Если true — уникальные
  перестановки, максимум 6; при одинаковых размерах первая по указанному порядку.
- Геометрия ортогональная. Для `heuristic` товар стоит на дне или имеет опору
  минимум под 80% площади основания от ранее уложенных товаров. Для `z3`, включая
  его резервную эвристику, требуется 100% опоры; несколько товаров могут совместно
  поддерживать основание. Порог не является настройкой HTTP v1. Центр масс, хрупкость,
  нагрузки, зазоры и траектория загрузки не моделируются; доля опоры не доказывает
  механическую устойчивость всей укладки.

## Входные модели

| Модель | Поля |
|---|---|
| BoxType | id, name, length, width, height, max_weight, available_count |
| Product | id, name, length, width, height, weight, quantity, allow_rotation=true |
| PackingOptions | include_alternatives=true, max_alternatives=3 (0..5), algorithm="heuristic" (`heuristic/z3`), solver_timeout_ms=10000 (>0), solver_workers=4 (>0; фактически не больше доступных CPU) |
| PackingRequest | boxes: BoxType[], products: Product[], options: PackingOptions={} |

ID: `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, уникален внутри своего массива.
Название: непустая строка до 200 символов, пробелы по краям удаляются.
Размеры: 1..100000 мм. Вес/max_weight: 1..100000000 г.
available_count: неотрицательное целое; quantity: положительное целое.
Фиксированных пределов числа единиц, строк товаров и типов коробок нет.
Frontend требует точного представления целых чисел в JavaScript; каталог хранит остаток в PostgreSQL BIGINT. Дроби, строки вместо чисел,
булевы вместо чисел и неизвестные поля отклоняются с HTTP 422.
`products` непустой; `boxes=[]` допустим как предметно невозможный заказ.
Нулевой остаток допустим и должен учитываться движком, не удаляться из запроса.

Новые настройки optional: старый запрос продолжает использовать прежнюю эвристику.
solver_timeout_ms и solver_workers применяются только к Z3. Число процессов
ограничивается доступными CPU и серверной конкуренцией; это верхняя граница запроса.
Таймаут относится к фазе Z3 (включая запуск/построение модели); подготовка резервного
плана и проверка/сериализация могут добавить время.

## Результат и доменные модели

Все перечисленные поля присутствуют в JSON; optional-ссылки инструкций равны `null`.
В домене массивы представлены tuple; `boxes_by_type` — dict[str,int].

| Модель | Поля и значение |
|---|---|
| ItemInstance | id=`{product_id}:{unit_index}`, product_id, name, unit_index (1-based), length, width, height, weight, allow_rotation |
| Position | x, y, z — неотрицательные целые мм |
| Dimensions | length, width, height — фактические размеры после поворота |
| Placement | item_instance_id, product_id, position, dimensions, orientation, step |
| PackedBox | id=`{box_type_id}:{index}`, box_type_id, name, length, width, height, max_weight, total_weight, used_volume, fill_ratio, placements[], instructions[] |
| PackingMetrics | total_items, packed_items, unpacked_items, boxes_used, boxes_by_type, total_box_volume, used_volume, empty_volume, fill_ratio, total_weight |
| PackingIssue | code, severity (`info/warning/error`), message, item_instance_ids[], box_type_ids[] |
| PackingInstructionStep | step, action, box_id, message, item_instance_id, product_id, position, dimensions, orientation |
| PackingAlternative | id, description, status, metrics, packed_boxes[], unpacked_items[], issues[] |
| PackingResult | status, metrics, packed_boxes[], unpacked_items[], issues[], alternatives[], algorithm_version, optimization=null |
| OptimizationInfo | status (`optimal/feasible/fallback`), reason (`completed/time_limit/size_limit/solver_error`), workers (реально запущенные процессы, >=0), time_limit_ms, support_ratio=1.0 |

`optimization` отсутствует в старых fixtures или равно null у обычной эвристики.
При выборе Z3 оно обязательно: `optimal` означает доказанный оптимум **основного**
плана по четырём целям Z3 и его модели полной опоры; `feasible` — допустимый план
без доказательства оптимальности; `fallback` — явно обозначенный результат
резервной эвристики с полной опорой. `workers=0` означает, что процессы Z3 не запускались.
`success` описывает полноту упаковки, а не доказательство оптимальности.

`fill_ratio` — доля 0..1, округление до 6 знаков; общий коэффициент взвешен по
объёму коробок. Для нуля коробок равен 0. `total_weight` учитывает только уложенные
товары, без тары. `used_volume` — сумма объёмов уложенных единиц;
`empty_volume=total_box_volume-used_volume`. `boxes_by_type` содержит только
использованные типы. Не возвращать пустые коробки.

`success`: все единицы размещены. `partial`: размещена хотя бы одна, но не все.
`impossible`: ни одной. Для валидного произвольного заказа это ожидаемые HTTP 200
результаты действующего движка, а не ошибки транспорта.

Коды issues: `ITEM_TOO_LARGE`, `ITEM_TOO_HEAVY`, `BOX_STOCK_EXHAUSTED`,
`NO_BOX_TYPES`, `NO_FEASIBLE_PLACEMENT`, `PARTIAL_PACKING`, `SIMILAR_ALTERNATIVES`,
`DEMO_STUB`. Причины объясняются по-русски. `NO_FEASIBLE_PLACEMENT` означает, что
поиск не нашёл размещение; сам код не является доказательством невозможности.
Каждая неуложенная единица должна присутствовать в `unpacked_items` и быть связана
с объясняющим issue. Альтернативы — полноценные планы, без рекурсивных alternatives.
Если альтернативы отключены или max_alternatives=0, возвращается пустой массив.

## Инструкции и детерминизм

- Единицы разворачиваются по product.id (лексикографически), затем unit_index численно.
- Для `heuristic` одинаковый ввод и версия движка дают одинаковый JSON. Нет UUID,
  времени выполнения, timestamp, случайных цветов или случайного seed в результате.
- Вход обоих алгоритмов канонизируется по id. Для `heuristic` перестановка строк
  boxes/products не меняет результат. Z3 с несколькими процессами и лимитом времени
  может вернуть разные равнозначные размещения и разный прогресс поиска в зависимости
  от CPU; побайтовый детерминизм для этого режима не обещается.
- PackedBox упорядочены по порядку открытия; index для каждого типа начинается с 1.
- placements упорядочены по step. step начинается с 1 и непрерывен внутри коробки.
- instructions: шаг 0 `prepare_box`, шаги 1..N `place_item`, N+1 `close_box`.
  У place_item ссылки, позиция, ориентация и размеры точно совпадают с Placement.
  У prepare/close ссылки на товар и геометрию null. box_id присутствует всегда.
- Сервис генерирует русские инструкции из placements и входных товаров, движку
  разрешено возвращать `PackedBox.instructions=()`. Не дублировать генерацию в UI.
- При показе шага k товары со step < k уже уложены, step = k — текущий,
  step > k скрыты. На prepare коробка пуста, на close показаны все товары.
- unpacked_items упорядочены по product_id и unit_index; issues — по code и
  item_instance_ids; альтернативы — по числу неуложенных единиц, числу коробок,
  пустому объёму, затем id. Все tie-break правила не зависят от hash Python.

## REST API /api/v1

| Метод | URL | Ответ |
|---|---|---|
| GET | /health | 200 `{status:"ok",api_version:"v1",engine:"candidate-packing-v1"}` |
| GET | /boxes | 200 BoxType[] (по id) |
| POST | /boxes | BoxType → 201 BoxType; дубликат id → 409 |
| PUT | /boxes/{id} | полная BoxType → 200; id тела должен совпасть с URL |
| DELETE | /boxes/{id} | 204 без тела; отсутствие → 404 |
| POST | /pack | PackingRequest → 200 PackingResult |
| POST | /pack/jobs | PackingRequest → 202 `{id,status,error,elapsed_seconds,timeout_seconds}` |
| GET | /pack/jobs/{id} | состояние фонового расчёта |
| GET | /pack/jobs/{id}/result | 200 PackingResult JSON; до готовности → 409 |
| DELETE | /pack/jobs/{id} | остановка фонового расчёта → 204 |
| GET | /demo/scenarios | 200 `[{id,name,description,expected_status}]` |
| GET | /demo/scenarios/{id} | 200 PackingRequest; отсутствие → 404 |

POST /pack всегда получает явный snapshot boxes. Каталог /boxes хранится только в PostgreSQL,
при первом запуске заполняется демо-типами; удалённые записи не восстанавливаются
при перезапуске. Расчёт не резервирует и не списывает остатки и не сохраняет заказ.
Это позволяет сравнивать планы без побочных эффектов. Orders/history отложены.

Фоновые состояния: `running/completed/failed/cancelled`. `timeout_seconds=null`
означает отсутствие общего ограничения времени; отдельный бюджет Z3 сохраняется.
Одновременно выполняется один фоновый заказ (второй → 409). Результаты временные:
до трёх последних задач, URL истекает через 15 минут после завершения. Штатный
запуск — один Uvicorn процесс. При рестарте задачи исчезают, каталог сохраняется.
UI выбирает фон для >1000 единиц или поиска >60 секунд; это пороги выбора транспорта,
не ограничения допустимого запроса. Серверное demo `large-order` генерируется
тем же кодом, что CLI; готового ответа для него нет.

**Основной серверный режим:** `DeterministicPackingEngine`, версия
`candidate-packing-v1`, вычисляет размещения для любого валидного входа в пределах
ограничений API. До 12 детерминированных стартов; до трёх найденных альтернатив,
не более запрошенного max_alternatives. Отсутствие альтернатив допустимо.
Результат не обязан повторять статические fixture-размещения.

`PackingEngineDispatcher` выбирает этот алгоритм по умолчанию либо `Z3PackingEngine`
при `options.algorithm="z3"`. `/health.engine` сохраняет версию default-алгоритма;
фактический результат описывают `algorithm_version` и `optimization`.
Z3 решает целочисленную модель: максимум количества упакованных единиц → максимум
их объёма → минимум использованных коробок → минимум их суммарного объёма.
Цены коробок в контракте нет. Прежние пределы 16 экземпляров / 64 слота сняты.
Полезные слоты: сумма `min(stock, item_count)` по совместимым типам.
При исчерпании выбранного времени возвращается лучший допустимый план, в том числе
явно обозначенный резерв `fallback/time_limit`. Все единицы остаются в задаче.
Ограничения и доказательство оптимальности подробнее в [Z3_ENGINE.md](Z3_ENGINE.md).

**Автономный demo-режим frontend:** воспроизводит `demo/*.request.json` /
`.response.json`, всегда показывает DEMO_STUB / demo-stub-v1. Изменённый
заказ в этом режиме даёт ENGINE_NOT_IMPLEMENTED; для него нужно выбрать сервер.
Python DemoPackingEngine сохранён как явно подключаемый fixture adapter;
default app factory его не использует.

Ошибки всегда имеют оболочку:

```json
{"error":{"code":"VALIDATION_ERROR","message":"Запрос не прошёл проверку.","details":[{"field":"body.products.0.length","message":"Input should be greater than 0","type":"greater_than"}]}}
```

Коды HTTP: 422 `VALIDATION_ERROR` (включая синтаксически некорректный JSON),
400 `HTTP_ERROR` (например, тело в некорректной UTF-8 кодировке), 404 `NOT_FOUND`,
409 `CONFLICT`, 500 `INTERNAL_ERROR`. `ENGINE_NOT_IMPLEMENTED` / 503 используется
только fixture-adapter, а не стандартным серверным расчётом.
details — массив `{field,message,type}`, пустой для ошибок без привязки к полю.
Не показывать traceback, SQL или внутренние пути клиенту.
Неподдерживаемый HTTP-метод: 405 `METHOD_NOT_ALLOWED`, с заголовком Allow.

## Пример запроса

```json
{
  "boxes": [{"id":"box-s","name":"Коробка S","length":300,"width":200,"height":150,"max_weight":5000,"available_count":5}],
  "products": [{"id":"tea","name":"Чай, подарочная упаковка","length":100,"width":80,"height":60,"weight":250,"quantity":2,"allow_rotation":true}],
  "options": {"include_alternatives":true,"max_alternatives":3}
}
```

Полные статические примеры запросов и ответов (включая инструкции, метрики,
success/partial/impossible) хранятся попарно в `demo/`; реальные ответы проверяются
по геометрии, метрикам и инструкциям, а не по совпадению со статическим планом.
Фрагмент Placement для второго товара простого сценария:

```json
{"item_instance_id":"tea:2","product_id":"tea","position":{"x":100,"y":0,"z":0},"dimensions":{"length":100,"width":80,"height":60},"orientation":"LWH","step":2}
```

Точка подключения движка: `app.domain.interfaces.PackingEngine.pack(request)`;
сервис получает реализацию через конструктор, FastAPI — через app factory.
Frontend использует контрактные типы `frontend/src/types/packing.ts`.
