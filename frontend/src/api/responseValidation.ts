import { ApiError } from './client';
import { isRecord, validateBox, validateRequest } from './validation';

type Guard = (value: unknown) => boolean;
const text: Guard = (value) => typeof value === 'string';
const integer: Guard = (value) =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0;
const positive: Guard = (value) => integer(value) && (value as number) > 0;
const ratio: Guard = (value) =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
const boolean: Guard = (value) => typeof value === 'boolean';
const oneOf =
  (...values: string[]): Guard =>
  (value) =>
    typeof value === 'string' && values.includes(value);
const arrayOf =
  (guard: Guard): Guard =>
  (value) =>
    Array.isArray(value) && value.every(guard);
const nullable =
  (guard: Guard): Guard =>
  (value) =>
    value === null || guard(value);
const optional =
  (guard: Guard): Guard =>
  (value) =>
    value === undefined || guard(value);
const shape =
  (fields: Record<string, Guard>): Guard =>
  (value) =>
    isRecord(value) && Object.entries(fields).every(([key, guard]) => guard(value[key]));
const dimensions = { length: positive, width: positive, height: positive };
const orientation = oneOf('LWH', 'LHW', 'WLH', 'WHL', 'HLW', 'HWL');
const position = shape({ x: integer, y: integer, z: integer });
const status = oneOf('success', 'partial', 'impossible');
const issue = shape({
  code: text,
  severity: oneOf('info', 'warning', 'error'),
  message: text,
  item_instance_ids: arrayOf(text),
  box_type_ids: arrayOf(text),
});
const placement = shape({
  item_instance_id: text,
  product_id: text,
  position,
  dimensions: shape(dimensions),
  orientation,
  step: positive,
});
const instruction = shape({
  step: integer,
  action: oneOf('prepare_box', 'place_item', 'close_box'),
  box_id: text,
  message: text,
  item_instance_id: nullable(text),
  product_id: nullable(text),
  position: nullable(position),
  dimensions: nullable(shape(dimensions)),
  orientation: nullable(orientation),
});
const item = shape({
  ...dimensions,
  id: text,
  product_id: text,
  name: text,
  unit_index: positive,
  weight: positive,
  allow_rotation: boolean,
});
const packedBox = shape({
  ...dimensions,
  id: text,
  box_type_id: text,
  name: text,
  max_weight: positive,
  total_weight: integer,
  used_volume: integer,
  fill_ratio: ratio,
  placements: arrayOf(placement),
  instructions: arrayOf(instruction),
});
const metrics = shape({
  total_items: integer,
  packed_items: integer,
  unpacked_items: integer,
  boxes_used: integer,
  boxes_by_type: (value) => isRecord(value) && Object.values(value).every(integer),
  total_box_volume: integer,
  used_volume: integer,
  empty_volume: integer,
  fill_ratio: ratio,
  total_weight: integer,
});
const plan = {
  status,
  metrics,
  packed_boxes: arrayOf(packedBox),
  unpacked_items: arrayOf(item),
  issues: arrayOf(issue),
};

export const responseGuards = {
  health: shape({ status: oneOf('ok'), api_version: oneOf('v1'), engine: text }),
  boxes: arrayOf((value) => Object.keys(validateBox(value)).length === 0),
  box: (value: unknown) => Object.keys(validateBox(value)).length === 0,
  scenarios: arrayOf(shape({ id: text, name: text, description: text, expected_status: status })),
  request: (value: unknown) => Object.keys(validateRequest(value)).length === 0,
  result: shape({
    ...plan,
    alternatives: arrayOf(shape({ ...plan, id: text, description: text })),
    algorithm_version: text,
    calculation_seconds: optional(nullable((value) => typeof value === 'number' && Number.isFinite(value) && value >= 0)),
    optimization: optional(nullable(shape({
      status: oneOf('optimal', 'feasible', 'fallback'),
      reason: oneOf('completed', 'time_limit', 'size_limit', 'resource_limit', 'solver_error'),
      workers: integer,
      time_limit_ms: (value) => value === null || (integer(value) && (value as number) > 0),
      support_ratio: ratio,
    }))),
  }),
};

/** Validate the response boundary before malformed server data can crash a result view. */
export async function checkedResponse<T>(promise: Promise<T>, guard: Guard): Promise<T> {
  const value = await promise;
  if (!guard(value))
    throw new ApiError(
      'Сервис вернул неполный или некорректный ответ. Повторите попытку или проверьте подключение API.',
      'INVALID_RESPONSE',
    );
  return value;
}
