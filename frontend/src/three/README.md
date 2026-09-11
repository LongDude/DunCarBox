# Будущий 3D-модуль

React Three Fiber и Three.js уже объявлены в `package.json`. Foundation не содержит viewer.

Источники: `docs/CONTRACTS.md` и `docs/UX.md`. Типы брать из `src/types/packing.ts`.
Отображение координат: `(x,y,z) → (x,z,-y)`; `Placement.position` — минимальный угол.
Центр mesh: `(x + length/2, z + height/2, -(y + width/2))`.
Размеры mesh: `(length, height, width)` из ориентированных `Placement.dimensions`.
Не применять ориентацию повторно: `dimensions` уже учитывает поворот.
