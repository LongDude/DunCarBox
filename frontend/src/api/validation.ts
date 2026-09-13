import { ApiError } from './client';
import type { ApiErrorDetail } from '../types/packing';

export type FieldErrors = Record<string, string>;
type RecordValue = Record<string, unknown>;

export const inputLimits = {
  dimension: 100_000,
  weight: 100_000_000,
  boxCount: Number.MAX_SAFE_INTEGER,
  productQuantity: Number.MAX_SAFE_INTEGER,
  totalItems: Number.MAX_SAFE_INTEGER,
  boxTypes: Number.MAX_SAFE_INTEGER,
  productTypes: Number.MAX_SAFE_INTEGER,
} as const;

export function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function numberError(value: unknown, min: number, max: number): string | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value)) return 'Введите целое число.';
  if (!Number.isSafeInteger(value)) return 'Слишком большое число. Уменьшите значение.';
  if (value < min || value > max)
    return `Допустимо от ${min.toLocaleString('ru-RU')} до ${max.toLocaleString('ru-RU')}.`;
}

function unknownFields(value: RecordValue, allowed: string[], errors: FieldErrors) {
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) errors[key] = 'Это поле не поддерживается API v1.';
  }
}

function validateEntry(value: unknown, kind: 'box' | 'product'): FieldErrors {
  if (!isRecord(value)) return { '': 'Укажите все поля строки.' };
  const errors: FieldErrors = {};
  const common = ['id', 'name', 'length', 'width', 'height'];
  unknownFields(
    value,
    [
      ...common,
      ...(kind === 'box'
        ? ['max_weight', 'available_count']
        : ['weight', 'quantity', 'allow_rotation']),
    ],
    errors,
  );
  if (typeof value.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(value.id)) {
    errors.id = '1–64 символа: латинские буквы, цифры, «-», «_». Первый символ — буква или цифра.';
  }
  if (typeof value.name !== 'string' || !value.name.trim() || value.name.trim().length > 200) {
    errors.name = 'Введите название от 1 до 200 символов.';
  }
  const fields: Array<[string, number, number]> = [
    ['length', 1, inputLimits.dimension],
    ['width', 1, inputLimits.dimension],
    ['height', 1, inputLimits.dimension],
    ...(kind === 'box'
      ? ([
          ['max_weight', 1, inputLimits.weight],
          ['available_count', 0, inputLimits.boxCount],
        ] as Array<[string, number, number]>)
      : ([
          ['weight', 1, inputLimits.weight],
          ['quantity', 1, inputLimits.productQuantity],
        ] as Array<[string, number, number]>)),
  ];
  for (const [field, min, max] of fields) {
    const error = numberError(value[field], min, max);
    if (error) errors[field] = error;
  }
  if (
    kind === 'product' &&
    value.allow_rotation !== undefined &&
    typeof value.allow_rotation !== 'boolean'
  ) {
    errors.allow_rotation = 'Выберите, разрешён ли поворот товара.';
  }
  return errors;
}

/** Catalog errors have local names (length); request errors use products.0.length. */
export function validateBox(value: unknown): FieldErrors {
  return validateEntry(value, 'box');
}

export function validateRequest(value: unknown): FieldErrors {
  if (!isRecord(value)) return { request: 'Заполните заказ.' };
  const errors: FieldErrors = {};
  unknownFields(value, ['boxes', 'products', 'options'], errors);
  for (const [key, kind, limit] of [
    ['boxes', 'box', inputLimits.boxTypes],
    ['products', 'product', inputLimits.productTypes],
  ] as const) {
    const entries = value[key];
    if (!Array.isArray(entries)) {
      errors[key] = key === 'products' ? 'Добавьте товары в заказ.' : 'Выберите доступные коробки.';
      continue;
    }
    if (entries.length > limit) errors[key] = `Допустимо не более ${limit} строк.`;
    if (key === 'products' && entries.length === 0) errors[key] = 'Добавьте хотя бы один товар.';
    const seen = new Map<unknown, number>();
    entries.forEach((entry: unknown, index: number) => {
      for (const [field, message] of Object.entries(validateEntry(entry, kind))) {
        errors[`${key}.${index}${field ? `.${field}` : ''}`] = message;
      }
      if (isRecord(entry)) {
        const previous = seen.get(entry.id);
        if (previous !== undefined) {
          errors[`${key}.${index}.id`] = 'Идентификатор должен быть уникальным в этом списке.';
          errors[`${key}.${previous}.id`] = 'Идентификатор должен быть уникальным в этом списке.';
        } else seen.set(entry.id, index);
      }
    });
  }
  if (Array.isArray(value.products)) {
    const total = value.products.reduce(
      (sum, entry: unknown) =>
        sum + (isRecord(entry) && typeof entry.quantity === 'number' ? entry.quantity : 0),
      0,
    );
    if (total > inputLimits.totalItems)
      errors.products = 'Общее количество превышает точность целых чисел в браузере.';
  }
  if (value.options !== undefined) {
    if (!isRecord(value.options)) errors.options = 'Некорректные настройки расчёта.';
    else {
      const optionErrors: FieldErrors = {};
      unknownFields(
        value.options,
        ['include_alternatives', 'max_alternatives', 'algorithm', 'solver_timeout_ms', 'solver_workers'],
        optionErrors,
      );
      if (
        value.options.include_alternatives !== undefined &&
        typeof value.options.include_alternatives !== 'boolean'
      ) {
        optionErrors.include_alternatives = 'Выберите, нужны ли альтернативные планы.';
      }
      if (value.options.max_alternatives !== undefined) {
        const error = numberError(value.options.max_alternatives, 0, 5);
        if (error) optionErrors.max_alternatives = error;
      }
      if (
        value.options.algorithm !== undefined &&
        value.options.algorithm !== 'heuristic' &&
        value.options.algorithm !== 'z3'
      ) optionErrors.algorithm = 'Выберите эвристику или оптимизатор Z3.';
      for (const [field, min, max] of [
        ['solver_timeout_ms', 1, Number.MAX_SAFE_INTEGER],
        ['solver_workers', 1, Number.MAX_SAFE_INTEGER],
      ] as const) {
        if (field === 'solver_timeout_ms' && value.options[field] === null) continue;
        if (value.options[field] !== undefined) {
          const error = numberError(value.options[field], min, max);
          if (error) optionErrors[field] = error;
        }
      }
      for (const [field, message] of Object.entries(optionErrors))
        errors[`options.${field}`] = message;
    }
  }
  return errors;
}

export function assertValid(errors: FieldErrors): void {
  if (Object.keys(errors).length) {
    throw new ApiError(
      'Проверьте отмеченные поля.',
      'VALIDATION_ERROR',
      422,
      Object.entries(errors).map(([field, message]) => ({
        field: `body.${field}`,
        message,
        type: 'frontend_validation',
      })),
    );
  }
}

export function fieldLabel(field: string): string {
  const path = field.replace(/^body\.?/, '').split('.');
  const labels: Record<string, string> = {
    id: 'Идентификатор',
    name: 'Название',
    length: 'Длина, мм',
    width: 'Ширина, мм',
    height: 'Высота, мм',
    weight: 'Вес, г',
    max_weight: 'Макс. вес, г',
    quantity: 'Количество, шт.',
    available_count: 'Остаток, шт.',
    allow_rotation: 'Поворот',
    boxes: 'Коробки',
    products: 'Товары',
    options: 'Настройки',
    include_alternatives: 'Альтернативные планы',
    max_alternatives: 'Количество альтернатив',
    algorithm: 'Алгоритм расчёта',
    solver_timeout_ms: 'Устаревший параметр времени, мс',
    solver_workers: 'Параллельные процессы',
  };
  if ((path[0] === 'products' || path[0] === 'boxes') && /^\d+$/.test(path[1] ?? '')) {
    return `${path[0] === 'products' ? 'Товар' : 'Коробка'} ${Number(path[1]) + 1}${path[2] ? ` · ${labels[path[2]] ?? 'Поле'}` : ''}`;
  }
  return labels[path.at(-1) ?? ''] ?? 'Заказ';
}

export function apiErrorDetailMessage(detail: ApiErrorDetail): string {
  if (/[а-яё]/i.test(detail.message)) return detail.message;
  if (detail.field.endsWith('solver_timeout_ms')) return 'Удалите устаревший параметр solver_timeout_ms или укажите null. Z3 работает без ограничения времени.';
  if (detail.field.endsWith('solver_workers')) return 'Укажите положительное целое число процессов.';
  if (detail.field.endsWith('algorithm')) return 'Выберите эвристику или оптимизатор Z3.';
  const labels: Record<string, string> = {
    missing: 'Заполните поле.',
    int_type: 'Введите целое число.',
    int_parsing: 'Введите целое число.',
    bool_type: 'Выберите допустимое значение.',
    string_type: 'Введите текст.',
    string_too_short: 'Поле не должно быть пустым.',
    string_too_long: 'Сократите название до 200 символов.',
    string_pattern_mismatch: 'Используйте латинские буквы, цифры, «-» и «_» в идентификаторе.',
    greater_than: 'Значение должно быть больше нуля.',
    greater_than_equal: 'Значение не может быть отрицательным.',
    less_than_equal: 'Превышено допустимое максимальное значение.',
    extra_forbidden: 'Это поле не поддерживается API v1.',
    too_long: 'Превышено допустимое количество строк.',
    too_short: 'Добавьте хотя бы одну строку.',
  };
  if (detail.message.includes('duplicate id')) return 'Идентификаторы строк не должны повторяться.';
  return labels[detail.type] ?? 'Проверьте значение и допустимые ограничения.';
}

export function apiErrorFields(error: ApiError): FieldErrors {
  return Object.fromEntries(
    error.details.map((detail) => [
      detail.field.replace(/^body\.?/, ''),
      apiErrorDetailMessage(detail),
    ]),
  );
}
