import type {
  Dimensions,
  PackedBox,
  PackingAlternative,
  PackingIssue,
  PackingRequest,
  PackingResult,
  PackingStatus,
  Placement,
  Product,
} from '../../types/packing';

export type PackingPlan = Pick<
  PackingResult,
  'status' | 'metrics' | 'packed_boxes' | 'unpacked_items' | 'issues'
>;
export const number = (value: number) =>
  value.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
export const percent = (value: number) => `${number(value * 100)}%`;
export const weight = (grams: number) =>
  `${(grams / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 3 })} кг`;
export const dimensions = (value: Dimensions) =>
  `${number(value.length)} × ${number(value.width)} × ${number(value.height)} мм`;

export const issueLabels: Record<PackingIssue['code'], string> = {
  ITEM_TOO_LARGE: 'Товар не помещается',
  ITEM_TOO_HEAVY: 'Превышен допустимый вес',
  BOX_STOCK_EXHAUSTED: 'Недостаточно коробок',
  NO_BOX_TYPES: 'Нет доступных типов коробок',
  NO_FEASIBLE_PLACEMENT: 'Размещение не найдено',
  PARTIAL_PACKING: 'Заказ упакован частично',
  SIMILAR_ALTERNATIVES: 'Похожие варианты',
  DEMO_STUB: 'Демонстрационный план',
};

export function issueMessage(issue: PackingIssue): string {
  return issue.code === 'NO_FEASIBLE_PLACEMENT'
    ? 'Алгоритму не удалось найти корректное размещение при текущих ограничениях.'
    : issue.message;
}

export function statusDisplay(status: PackingStatus, issues: PackingIssue[] = []) {
  if (status === 'success') return { label: 'Заказ упакован', symbol: '✓', tone: 'success' };
  if (status === 'partial') return { label: 'Упакован частично', symbol: '!', tone: 'partial' };
  return {
    label: issues.some((issue) => issue.code === 'NO_FEASIBLE_PLACEMENT')
      ? 'Не удалось найти размещение'
      : 'Невозможно упаковать заказ',
    symbol: '×',
    tone: 'impossible',
  };
}

export function selectPlan(result: PackingResult, alternativeId: string | null): PackingPlan {
  return result.alternatives.find((alternative) => alternative.id === alternativeId) ?? result;
}

export function instructionAt(box: PackedBox, step: number) {
  return box.instructions.find((instruction) => instruction.step === step);
}

export function getPlacement(box: PackedBox, step: number) {
  return box.placements.find((placement) => placement.step === step);
}

export function productFor(placement: Placement, products: Product[]) {
  return products.find((product) => product.id === placement.product_id);
}

export function instanceLabel(placement: Placement, products: Product[]) {
  const product = productFor(placement, products);
  const unit = placement.item_instance_id.slice(placement.product_id.length + 1);
  return `Экземпляр ${unit}${product ? ` из ${product.quantity}` : ''}`;
}

/** A spatial reading of contract coordinates, not a second packing/instruction engine.
 * Server steps and messages remain authoritative and are always available in details.
 * Relations are used only for coincident faces and aligned depth/elevation.
 */
export function placementGuidance(
  placement: Placement,
  box: PackedBox,
  products: Product[],
): string {
  const { x, y, z } = placement.position;
  if (x === 0 && y === 0 && z === 0)
    return 'Положите на дно, в передний левый угол коробки. Придвиньте к левой и передней стенкам.';
  const leftNeighbor = box.placements.find(
    (item) =>
      item.step < placement.step &&
      item.position.x + item.dimensions.length === x &&
      item.position.y === y &&
      item.position.z === z,
  );
  if (leftNeighbor) {
    const name = productFor(leftNeighbor, products)?.name ?? leftNeighbor.product_id;
    return `Положите вплотную справа от «${name}», на той же высоте. Выровняйте передние грани товаров.${z === 0 ? ' Товар должен стоять на дне.' : ''}`;
  }
  const surface =
    z === 0
      ? 'Положите товар на дно.'
      : `Расположите нижнюю грань товара на высоте ${number(z)} мм от дна.`;
  const horizontal =
    x === 0
      ? 'Придвиньте к левой стенке.'
      : `Оставьте ${number(x)} мм от левой стенки до левой грани товара.`;
  const depth =
    y === 0
      ? 'Придвиньте к передней стенке.'
      : `Оставьте ${number(y)} мм от передней стенки до передней грани товара.`;
  return `${surface} ${horizontal} ${depth}`;
}

export function orientationGuidance(placement: Placement): string {
  const d = placement.dimensions;
  return `Сторона ${number(d.length)} мм — вдоль длины коробки, ${number(d.width)} мм — вглубь, ${number(d.height)} мм — вверх.`;
}

export function planSteps(plan: PackingPlan): number {
  return plan.packed_boxes.reduce((sum, box) => sum + box.instructions.length, 0);
}

export function createExport(
  orderId: string,
  request: PackingRequest,
  result: PackingResult,
  selectedId: string | null,
) {
  const selected = result.alternatives.find((alternative) => alternative.id === selectedId);
  return {
    order_id: orderId,
    request,
    result,
    selected_plan_id: selected?.id ?? 'recommended',
    selected_plan: selected ?? result,
  };
}

export function downloadResult(
  orderId: string,
  request: PackingRequest,
  result: PackingResult,
  selectedId: string | null,
) {
  const blob = new Blob(
    [JSON.stringify(createExport(orderId, request, result, selectedId), null, 2)],
    { type: 'application/json;charset=utf-8' },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `packing-${orderId.replace(/[^a-zA-Z0-9а-яА-ЯёЁ_-]/g, '_').slice(0, 80) || 'order'}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function alternativeTitle(alternative: PackingAlternative, index: number): string {
  return alternative.description || `Вариант ${index + 2}`;
}
