import { describe, expect, it } from 'vitest';
import type {
  PackedBox,
  PackingAlternative,
  PackingIssue,
  PackingResult,
  Placement,
} from '../../types/packing';
import { demoFixtures } from '../demo/fixtures';
import {
  alternativeTitle,
  createExport,
  dimensions,
  getPlacement,
  instanceLabel,
  instructionAt,
  issueLabels,
  issueMessage,
  orientationGuidance,
  optimizationDisplay,
  percent,
  placementGuidance,
  planSteps,
  productFor,
  selectPlan,
  statusDisplay,
  weight,
} from './presentation';

const simple = demoFixtures['simple-order'];
const multiple = demoFixtures['multiple-boxes'];
const shortage = demoFixtures['stock-shortage'];
const oversized = demoFixtures.oversized;
const simpleBox = simple.response.packed_boxes[0];
const first = simpleBox.placements[0];

describe('honest optimizer result presentation', () => {
  const result = { ...simple.response, issues: [], algorithm_version: 'z3-packing-v1' };
  const request = { ...simple.request, options: { algorithm: 'z3' as const } };
  const optimization = { status: 'optimal' as const, reason: 'completed' as const, workers: 4, time_limit_ms: 10000, support_ratio: 1 };
  it('renders an unlimited solver without converting null to a zero-second timeout', () => {
    const display = optimizationDisplay({ ...result, optimization: { ...optimization, time_limit_ms: null } }, request);
    expect(display.detail).toContain('без ограничения времени');
    expect(display.detail).not.toContain('лимит поиска: 0');
    expect(display.title).toBe('Оптимум доказан в модели Z3');
  });
  it('distinguishes fixture playback, heuristics, proven optima and selected alternatives', () => {
    expect(optimizationDisplay(simple.response, simple.request).title).toBe('Без нового расчёта');
    expect(optimizationDisplay({ ...result, algorithm_version: 'candidate-packing-v1' }, request)).toMatchObject({ actual: 'Быстрая эвристика', title: 'Оптимум не доказан' });
    expect(optimizationDisplay({ ...result, optimization }, request).title).toBe('Оптимум доказан в модели Z3');
    expect(optimizationDisplay({ ...result, optimization }, request, true).detail).toContain('не к выбранной альтернативе');
  });
  it('does not label a time-limited feasible plan or fallback as proven optimal', () => {
    expect(optimizationDisplay({ ...result, optimization: { ...optimization, status: 'feasible', reason: 'time_limit' } }, request)).toMatchObject({ actual: 'Оптимизатор Z3', title: 'Найден допустимый план, оптимум не доказан', detail: expect.stringContaining('лимит времени') });
    expect(optimizationDisplay({ ...result, optimization: { ...optimization, status: 'fallback', reason: 'size_limit', workers: 0 } }, request)).toMatchObject({ actual: 'Быстрая эвристика', requested: 'Оптимизатор Z3', title: 'Использована резервная эвристика', detail: expect.stringContaining('Оптимум не доказан') });
  });
});

function issue(code: PackingIssue['code'], message = 'Объяснение сервера'): PackingIssue {
  return {
    code,
    message,
    severity: 'error',
    item_instance_ids: ['tea:1'],
    box_type_ids: ['box-s'],
  };
}

function alternative(id: string, result: PackingResult): PackingAlternative {
  return {
    id,
    description: `Серверный вариант ${id}`,
    status: result.status,
    metrics: result.metrics,
    packed_boxes: result.packed_boxes,
    unpacked_items: result.unpacked_items,
    issues: result.issues,
  };
}

describe('API status and diagnostic presentation', () => {
  it('distinguishes success, partial and a proven dimension constraint in canonical API responses', () => {
    expect(statusDisplay(simple.response.status, simple.response.issues)).toMatchObject({
      label: 'Заказ упакован',
      tone: 'success',
    });
    expect(statusDisplay(shortage.response.status, shortage.response.issues)).toMatchObject({
      label: 'Упакован частично',
      tone: 'partial',
    });
    expect(statusDisplay(oversized.response.status, oversized.response.issues)).toMatchObject({
      label: 'Невозможно упаковать заказ',
      tone: 'impossible',
    });
  });

  it('does not present a heuristic failure as proof that packing is impossible', () => {
    const reason = issue('NO_FEASIBLE_PLACEMENT', 'Эвристика не нашла укладку.');
    expect(statusDisplay('impossible', [reason]).label).toBe('Не удалось найти размещение');
    expect(issueMessage(reason)).toBe(
      'Алгоритму не удалось найти корректное размещение при текущих ограничениях.',
    );
    expect(statusDisplay('partial', [reason]).label).toBe('Упакован частично');
  });

  it('preserves specific server diagnostics and the demo marker', () => {
    const reason = issue(
      'BOX_STOCK_EXHAUSTED',
      'Для трёх наборов доступна только одна подходящая коробка.',
    );
    expect(issueMessage(reason)).toBe(reason.message);
    expect(issueMessage(simple.response.issues[0])).toBe(simple.response.issues[0].message);
    expect(issueLabels.DEMO_STUB).toBe('Демонстрационный план');
    expect(issueLabels.ITEM_TOO_HEAVY).toBe('Превышен допустимый вес');
    expect(issueLabels.NO_FEASIBLE_PLACEMENT).toBe('Размещение не найдено');
  });

  it('keeps millimetres, converts grams to kilograms and interprets fill ratio as a fraction', () => {
    expect(dimensions(simpleBox)).toBe('300 × 200 × 150 мм');
    expect(weight(1250)).toBe('1,25 кг');
    expect(weight(1)).toBe('0,001 кг');
    expect(percent(0.875)).toBe('87,5%');
    expect(percent(0)).toBe('0%');
  });
});

describe('server plans, instructions and export', () => {
  it('sorts cartons by fill descending without changing the source array', () => {
    const source = structuredClone(multiple.response);
    source.packed_boxes[0].fill_ratio = 0.2;
    source.packed_boxes[1].fill_ratio = 0.9;
    const plan = selectPlan(source, null);
    expect(plan.packed_boxes.map(box => box.fill_ratio)).toEqual([0.9, 0.2]);
    expect(source.packed_boxes.map(box => box.fill_ratio)).toEqual([0.2, 0.9]);
  });
  const altPartial = alternative('partial-plan', shortage.response);
  const altMultiple = alternative('multiple-plan', multiple.response);
  const result: PackingResult = { ...simple.response, alternatives: [altPartial, altMultiple] };

  it('selects every part of the alternative without mutating server plans', () => {
    const before = JSON.stringify(result);
    const plan = selectPlan(result, altPartial.id);
    expect(plan).toEqual(altPartial);
    expect(plan.status).toBe('partial');
    expect(plan.metrics).toBe(shortage.response.metrics);
    expect(plan.packed_boxes).toEqual(shortage.response.packed_boxes);
    expect(plan.unpacked_items).toBe(shortage.response.unpacked_items);
    expect(plan.issues).toBe(shortage.response.issues);
    expect(selectPlan(result, altMultiple.id)).toEqual(altMultiple);
    expect(JSON.stringify(result)).toBe(before);
  });

  it('uses the recommended plan for no selection or an unavailable alternative', () => {
    expect(selectPlan(result, null)).toEqual(result);
    expect(selectPlan(result, 'removed-plan')).toEqual(result);
  });

  it('keeps server alternative descriptions without inventing optimality or complexity labels', () => {
    expect(alternativeTitle(altPartial, 0)).toBe('Серверный вариант partial-plan');
    expect(alternativeTitle({ ...altPartial, description: '' }, 1)).toBe('Вариант 3');
  });

  it('exports order ID, the request snapshot, full API result and the selected plan consistently', () => {
    const exported = createExport('ORDER-17', simple.request, result, altMultiple.id);
    expect(exported.order_id).toBe('ORDER-17');
    expect(exported.request).toBe(simple.request);
    expect(exported.result).toBe(result);
    expect(exported.selected_plan_id).toBe(altMultiple.id);
    expect(exported.selected_plan).toBe(altMultiple);
    expect(JSON.parse(JSON.stringify(exported)).selected_plan.packed_boxes).toEqual(
      multiple.response.packed_boxes,
    );
  });

  it('exports the recommended plan ID when a stale selected alternative has disappeared', () => {
    const exported = createExport('ORDER-17', simple.request, result, 'removed-plan');
    expect(exported.selected_plan).toBe(result);
    expect(exported.selected_plan_id).toBe('recommended');
    expect(createExport('ORDER-17', simple.request, result, null).selected_plan_id).toBe(
      'recommended',
    );
  });

  it('reads server step identifiers independently of array indices and retains the original message', () => {
    const reordered: PackedBox = {
      ...simpleBox,
      instructions: [...simpleBox.instructions].reverse(),
      placements: [...simpleBox.placements].reverse(),
    };
    expect(instructionAt(reordered, 0)?.action).toBe('prepare_box');
    expect(instructionAt(reordered, 1)).toBe(simpleBox.instructions[1]);
    expect(instructionAt(reordered, 1)?.message).toBe(simpleBox.instructions[1].message);
    expect(getPlacement(reordered, 1)).toBe(first);
    expect(getPlacement(reordered, 0)).toBeUndefined();
    expect(getPlacement(reordered, 3)).toBeUndefined();
    expect(instructionAt(reordered, 99)).toBeUndefined();
  });

  it('counts server prepare, placement and close operations across all boxes', () => {
    expect(planSteps(simple.response)).toBe(4);
    expect(planSteps(multiple.response)).toBe(10);
    expect(planSteps(oversized.response)).toBe(0);
  });

  it('maps instance IDs back to the immutable request snapshot', () => {
    const second = simpleBox.placements[1];
    expect(productFor(second, simple.request.products)).toBe(simple.request.products[0]);
    expect(instanceLabel(second, simple.request.products)).toBe('Экземпляр 2 из 2');
    expect(instanceLabel(second, [])).toBe('Экземпляр 2');
  });
});

describe('truthful operator guidance derived from contract geometry', () => {
  it('identifies the front-left-bottom origin without guessing a back corner', () => {
    expect(placementGuidance(first, simpleBox, simple.request.products)).toBe(
      'Положите на дно, в передний левый угол коробки. Придвиньте к левой и передней стенкам.',
    );
  });

  it('uses a coincident earlier face to describe an actual left neighbour', () => {
    const guidance = placementGuidance(simpleBox.placements[1], simpleBox, simple.request.products);
    expect(guidance).toContain('справа от «Чай, подарочная упаковка»');
    expect(guidance).toContain('Выровняйте передние грани');
    expect(guidance).toContain('Товар должен стоять на дне');
  });

  it.each([
    { title: 'future operation', change: { step: 4 } },
    { title: 'different depth', change: { position: { x: 0, y: 20, z: 0 } } },
    { title: 'different height', change: { position: { x: 0, y: 0, z: 20 } } },
    { title: 'non-touching face', change: { dimensions: { length: 90, width: 80, height: 60 } } },
  ])('does not invent a neighbour relation for $title', ({ change }) => {
    const next = simpleBox.placements[1];
    const box: PackedBox = { ...simpleBox, placements: [{ ...first, ...change }, next] };
    const guidance = placementGuidance(next, box, simple.request.products);
    expect(guidance).not.toContain('справа от');
    expect(guidance).toContain('100 мм от левой стенки');
  });

  it('describes elevated positions without inventing a supporting product', () => {
    const elevated: Placement = { ...first, position: { x: 17, y: 42, z: 80 } };
    const guidance = placementGuidance(
      elevated,
      { ...simpleBox, placements: [elevated] },
      simple.request.products,
    );
    expect(guidance).toContain('нижнюю грань товара на высоте 80 мм');
    expect(guidance).toContain('17 мм от левой стенки');
    expect(guidance).toContain('42 мм от передней стенки');
    expect(guidance).not.toMatch(/поверх|сверху|слоем|на дно/);
  });

  it('uses already oriented dimensions for a real rotated API placement', () => {
    const rotated = multiple.response.packed_boxes[0].placements.find(
      (placement) => placement.orientation === 'WLH',
    )!;
    const product = productFor(rotated, multiple.request.products)!;
    expect(rotated.dimensions.length).toBe(product.width);
    expect(rotated.dimensions.width).toBe(product.length);
    expect(orientationGuidance(rotated)).toBe(
      'Сторона 80 мм — вдоль длины коробки, 120 мм — вглубь, 40 мм — вверх.',
    );
  });
});
