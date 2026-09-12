"""Минимальная стоимость трёхмерной упаковки с полной опорой основания.

Установка: python -m pip install z3-solver
Запуск:    python packing.py < input.txt > output.txt

Модель: прямоугольные жёсткие предметы; внутренние размеры коробок;
повороты на 90 градусов; суммарная масса не превышает лимит коробки.
Каждая точка основания стоит на дне или верхней грани другого предмета.
Несколько предметов могут совместно поддерживать один верхний предмет.
Свесы запрещены. Прочность самих предметов не ограничивается.

Ответ точный для этой модели, но время поиска не ограничено и может быть
очень большим. Это решение для небольшого общего числа экземпляров.
При невозможности упаковки выводится -1. Ошибка решателя не считается
доказательством невозможности: в этом случае программа завершается с кодом 2.

При целых размерах полная опора допускает целочисленное оптимальное
размещение. Округление всех нижних координат вниз сохраняет порядок
граней, непересечение, контакты и полное покрытие основания. Поэтому
использование целых координат здесь не ограничивает оптимум данной модели.
"""

import sys
from itertools import permutations

from z3 import And, Bool, If, Implies, Int, Optimize, Or, Sum, sat, unsat


def add_full_support(opt, box, x, y, z, X, Y, Z):
    """Запретить непокрытые участки основания, без перебора единичных ячеек."""
    count = len(box)
    for i in range(count):
        others = [j for j in range(count) if j != i]
        if not others:
            opt.add(z[i] == 0)
            continue

        # Возможные поверхности опоры: та же коробка, верх на уровне низа i.
        touching = [And(box[i] == box[j], Z[j] == z[i]) for j in others]

        # Любой непокрытый участок можно продолжить влево и назад до
        # левой/ближней грани i либо правой/дальней грани одной из опор.
        # Поэтому достаточно декартова произведения этих координат.
        xs = [x[i]] + [X[j] for j in others]
        ys = [y[i]] + [Y[j] for j in others]
        active = [True] + touching

        inside_x = [And(x[i] <= p, p < X[i]) for p in xs]
        inside_y = [And(y[i] <= q, q < Y[i]) for q in ys]
        covered_x = [[And(x[j] <= p, p < X[j]) for j in others] for p in xs]
        covered_y = [[And(y[j] <= q, q < Y[j]) for j in others] for q in ys]

        for a in range(len(xs)):
            for b in range(len(ys)):
                covered = Or([
                    And(touching[k], covered_x[a][k], covered_y[b][k])
                    for k in range(len(others))
                ])
                opt.add(Implies(
                    And(z[i] > 0, active[a], active[b], inside_x[a], inside_y[b]),
                    covered,
                ))


def pack(box_types, item_types):
    """Вернуть [(id коробки, [(id предмета, x, y, z, X, Y, Z), ...]), ...].

    box_types:  (id, количество, лимит массы, стоимость, длина, ширина, высота)
    item_types: (id, количество, масса, длина, ширина, высота)
    None означает доказанную невозможность размещения.
    """
    items = [
        (item_id, weight, a, b, c)
        for item_id, quantity, weight, a, b, c in item_types
        for _ in range(quantity)
    ]
    K = len(items)
    if K == 0:
        return []

    # Используемая коробка содержит хотя бы один предмет, поэтому K копий
    # каждого типа достаточно даже при большем количестве на складе.
    boxes = []
    previous_copy = []
    for box_id, quantity, capacity, price, a, b, c in box_types:
        previous = None
        for _ in range(min(quantity, K)):
            previous_copy.append(previous)
            previous = len(boxes)
            boxes.append((box_id, capacity, price, a, b, c))
    B = len(boxes)
    if B == 0:
        return None

    opt = Optimize()
    box = [Int(f"box_{i}") for i in range(K)]
    x = [Int(f"x_{i}") for i in range(K)]
    y = [Int(f"y_{i}") for i in range(K)]
    z = [Int(f"z_{i}") for i in range(K)]
    dx = [Int(f"dx_{i}") for i in range(K)]
    dy = [Int(f"dy_{i}") for i in range(K)]
    dz = [Int(f"dz_{i}") for i in range(K)]
    X = [x[i] + dx[i] for i in range(K)]
    Y = [y[i] + dy[i] for i in range(K)]
    Z = [z[i] + dz[i] for i in range(K)]
    used = [Bool(f"used_{b}") for b in range(B)]

    for i, (_, weight, a, b, c) in enumerate(items):
        opt.add(x[i] >= 0, y[i] >= 0, z[i] >= 0)
        rotations = sorted(set(permutations((a, b, c))))
        opt.add(Or([
            And(dx[i] == u, dy[i] == v, dz[i] == w)
            for u, v, w in rotations
        ]))

        candidates = []
        for j, (_, capacity, _, L, W, H) in enumerate(boxes):
            if weight <= capacity and any(
                u <= L and v <= W and w <= H for u, v, w in rotations
            ):
                candidates.append(box[i] == j)
                opt.add(Implies(box[i] == j, And(X[i] <= L, Y[i] <= W, Z[i] <= H)))
        if not candidates:
            return None
        opt.add(Or(candidates))

        # Экземпляры одного типа можно перенумеровать по номеру коробки.
        if i > 0 and items[i] == items[i - 1]:
            opt.add(box[i - 1] <= box[i])

    for j, (_, capacity, _, L, W, H) in enumerate(boxes):
        assigned = [box[i] == j for i in range(K)]
        opt.add(used[j] == Or(assigned))
        opt.add(Sum([If(assigned[i], items[i][1], 0) for i in range(K)]) <= capacity)
        opt.add(Sum([
            If(assigned[i], items[i][2] * items[i][3] * items[i][4], 0)
            for i in range(K)
        ]) <= L * W * H)
        if previous_copy[j] is not None:
            opt.add(Implies(used[j], used[previous_copy[j]]))

    # Два предмета в одной коробке разделены хотя бы по одной оси.
    for i in range(K):
        for j in range(i):
            opt.add(Or(
                box[i] != box[j],
                X[i] <= x[j], X[j] <= x[i],
                Y[i] <= y[j], Y[j] <= y[i],
                Z[i] <= z[j], Z[j] <= z[i],
            ))

    add_full_support(opt, box, x, y, z, X, Y, Z)

    opt.minimize(Sum([If(used[j], boxes[j][2], 0) for j in range(B)]))
    # При равной минимальной стоимости предпочитаем меньше коробок.
    opt.minimize(Sum([If(used[j], 1, 0) for j in range(B)]))

    status = opt.check()
    if status == unsat:
        return None
    if status != sat:
        raise RuntimeError("Оптимальность не доказана: " + opt.reason_unknown())

    model = opt.model()
    value = lambda variable: model.eval(variable).as_long()
    contents = [[] for _ in boxes]
    for i, item in enumerate(items):
        contents[value(box[i])].append((
            item[0], value(x[i]), value(y[i]), value(z[i]),
            value(X[i]), value(Y[i]), value(Z[i]),
        ))
    return [
        (boxes[j][0], sorted(group, key=lambda p: (p[3], p[2], p[1], p[0])))
        for j, group in enumerate(contents) if group
    ]


def read_input():
    values = list(map(int, sys.stdin.buffer.read().split()))
    if len(values) < 2:
        raise ValueError("Ожидаются n и m.")
    n, m = values[:2]
    if n < 0 or m < 0 or len(values) != 2 + 7 * n + 6 * m:
        raise ValueError("Неверное количество входных чисел.")
    boxes = [tuple(values[2 + 7 * i: 2 + 7 * (i + 1)]) for i in range(n)]
    start = 2 + 7 * n
    items = [tuple(values[start + 6 * i: start + 6 * (i + 1)]) for i in range(m)]
    for rows in (boxes, items):
        if len({row[0] for row in rows}) != len(rows):
            raise ValueError("id типов должны быть уникальны внутри своего списка.")
        for row in rows:
            if any(v < 0 for v in row[1:-3]) or any(v <= 0 for v in row[-3:]):
                raise ValueError("Размеры должны быть положительными, остальные величины — неотрицательными.")
    return boxes, items


def main():
    try:
        result = pack(*read_input())
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 2
    if result is None:
        print(-1)
        return 0
    print(len(result))
    for box_id, group in result:
        print(len(group), box_id)
        for item in group:
            print(*item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
