import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import type {
  BoxType,
  DemoScenario,
  PackingAlternative,
  PackingRequest,
  PackingResult,
} from '../src/types/packing';

function fixture<T>(name: string): T {
  return JSON.parse(
    readFileSync(
      new URL(`../src/features/demo/fixture-data/${name}.json`, import.meta.url),
      'utf8',
    ),
  ) as T;
}

const scenarios = fixture<DemoScenario[]>('scenarios');
const catalog = fixture<BoxType[]>('catalog.boxes');
const multipleRequest = fixture<PackingRequest>('multiple-boxes.request');
const multipleResult = fixture<PackingResult>('multiple-boxes.response');
const simpleRequest = fixture<PackingRequest>('simple-order.request');
const simpleResult = fixture<PackingResult>('simple-order.response');

async function loadOrder(page: Page, scenario = 'multiple-boxes', mode = 'demo') {
  await page.goto(`/?mode=${mode}`);
  await expect(page.getByLabel('Демо-сценарий')).toBeEnabled();
  await page.getByLabel('Демо-сценарий').selectOption(scenario);
  await page.getByRole('button', { name: 'Загрузить демо-заказ' }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue(`ДЕМО-${scenario}`);
}

async function calculate(page: Page) {
  await page.getByRole('button', { name: 'Рассчитать упаковку' }).click();
  await expect(page.locator('.result-screen h1')).toBeVisible();
}

async function jsonExport(
  page: Page,
): Promise<{
  order_id: string;
  request: PackingRequest;
  result: PackingResult;
  selected_plan_id: string;
  selected_plan: PackingAlternative | PackingResult;
}> {
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Экспорт JSON' }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toMatch(/^packing-.*\.json$/);
  const path = await download.path();
  expect(path).not.toBeNull();
  return JSON.parse(await readFile(path!, 'utf8'));
}

async function mockApi(page: Page, pack: (route: Pick<Route, 'request' | 'fulfill'>) => Promise<void>) {
  let result: PackingResult | undefined;
  const job = { id: 'a'.repeat(32), status: 'completed', error: null, elapsed_seconds: 1, timeout_seconds: null };
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/pack/jobs') return pack({
      request: () => route.request(),
      fulfill: async (options) => {
        if ((options?.status ?? 200) >= 400) return route.fulfill(options);
        result = options?.json as PackingResult;
        return route.fulfill({ status: 202, json: job });
      },
    });
    if (path.endsWith('/result')) return route.fulfill({ json: result });
    if (path === `/api/v1/pack/jobs/${job.id}`) return route.fulfill({ json: job });
    if (path === '/api/v1/health')
      return route.fulfill({ json: { status: 'ok', api_version: 'v1', engine: 'test-engine-v1' } });
    if (path === '/api/v1/boxes') return route.fulfill({ json: catalog });
    if (path === '/api/v1/demo/scenarios') return route.fulfill({ json: scenarios });
    const scenario = path.split('/').at(-1);
    if (scenarios.some((entry) => entry.id === scenario))
      return route.fulfill({ json: fixture(`${scenario}.request`) });
    return route.fulfill({
      status: 404,
      json: { error: { code: 'NOT_FOUND', message: 'Не найдено.', details: [] } },
    });
  });
}

test('Z3 settings survive demo mode and are exported with an unproven result', async ({ page }) => {
  let submitted: PackingRequest | undefined;
  const result: PackingResult = {
    ...structuredClone(simpleResult),
    algorithm_version: 'z3-packing-v1',
    issues: simpleResult.issues.filter(issue => issue.code !== 'DEMO_STUB'),
    optimization: { status: 'feasible', reason: 'time_limit', workers: 2, time_limit_ms: 3250, support_ratio: 1 },
  };
  await mockApi(page, async route => {
    submitted = route.request().postDataJSON() as PackingRequest;
    await route.fulfill({ json: result });
  });
  await loadOrder(page, 'simple-order', 'api');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('z3');
  await page.getByLabel('Лимит поиска, с', { exact: true }).fill('3.25');
  await page.getByLabel('Параллельные процессы', { exact: true }).fill('8');
  await page.getByLabel('Источник данных').selectOption('demo');
  await expect(page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true })).toHaveValue('demo');
  await page.getByLabel('Источник данных').selectOption('api');
  await expect(page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true })).toHaveValue('z3');
  await page.getByLabel('Демо-сценарий').selectOption('simple-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-simple-order');
  await calculate(page);
  expect(submitted?.options).toMatchObject({ algorithm: 'z3', solver_timeout_ms: 3250, solver_workers: 8 });
  const summary = page.getByRole('region', { name: 'Алгоритм и качество решения' });
  await expect(summary).toContainText('Найден допустимый план, оптимум не доказан');
  await expect(summary).toContainText('Достигнут лимит времени поиска');
  const exported = await jsonExport(page);
  expect(exported.request.options).toMatchObject(submitted!.options!);
  expect(exported.result.optimization).toEqual(result.optimization);
  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.print-instructions')).toContainText('Найден допустимый план, оптимум не доказан');
});

test('multiple boxes: 3D, step filtering, layer view, show all and box reset', async ({ page }) => {
  const runtimeErrors: string[] = [];
  page.on('pageerror', (error) => runtimeErrors.push(error.message));
  await loadOrder(page);
  await calculate(page);
  await expect(page.locator('.status-badge')).toContainText('Заказ упакован');
  await expect(page.locator('.box-selector > button')).toHaveCount(2);
  const fillWidth = await page
    .locator('.box-selector .fill-track > i')
    .first()
    .evaluate((element) => (element as HTMLElement).style.width);
  expect(Number.parseFloat(fillWidth) / 100).toBeCloseTo(
    multipleResult.packed_boxes[0].fill_ratio,
    6,
  );
  await expect(page.locator('.packing-viewer canvas')).toBeVisible();
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  await expect(page.getByRole('button', { name: '← Назад', exact: true })).toBeDisabled();

  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  await expect(page.locator('.step-counter')).toHaveText('1 / 4');
  await expect(page.locator('.viewer-scene-label')).toContainText('Шаг 1');
  await expect(page.locator('.current-instruction')).toContainText('Положение упаковки');
  await page.getByRole('button', { name: 'По слоям', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(1);
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveAttribute(
    'aria-label',
    /текущий товар/,
  );
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(2);
  await page.getByRole('button', { name: '← Назад', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Показать всё', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(3);
  await expect(page.getByRole('button', { name: 'Вернуться к шагу', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );

  await page.locator('.box-selector > button').nth(1).click();
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  await expect(page.getByRole('button', { name: 'Показать всё', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await page.getByRole('button', { name: 'По слоям', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(0);
  await page.locator('.step-list summary').click();
  await page.getByRole('button', { name: 'Проверка и закрытие' }).click();
  await expect(page.locator('.step-counter')).toHaveText('4 / 4');
  await expect(page.getByRole('button', { name: 'Все шаги пройдены' })).toBeDisabled();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(3);

  await page.locator('.box-selector > button').first().click();
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  await page.locator('.step-list summary').click();
  await page.getByRole('button', { name: 'Проверка и закрытие' }).click();
  await page.getByRole('button', { name: 'Следующая коробка →', exact: true }).click();
  await expect(page.locator('.box-selector > button').nth(1)).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  expect(runtimeErrors).toEqual([]);
});

test('JSON and print include every box, complete steps and the order snapshot', async ({
  page,
}) => {
  await loadOrder(page);
  await calculate(page);
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  const exported = await jsonExport(page);
  expect(exported.order_id).toBe('ДЕМО-multiple-boxes');
  expect(exported.request.products).toEqual(multipleRequest.products);
  expect(exported.result.packed_boxes).toHaveLength(2);
  expect(exported.selected_plan.packed_boxes).toHaveLength(2);
  expect(exported.selected_plan_id).toBe('recommended');
  expect(exported.selected_plan.packed_boxes.flatMap((box) => box.instructions)).toHaveLength(10);

  await page.evaluate(() => {
    window.print = () => {
      document.documentElement.dataset.printInvoked = 'yes';
    };
  });
  await page.getByRole('button', { name: 'Печать / PDF', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-print-invoked', 'yes');
  await expect(page.locator('.print-instructions')).toBeHidden();
  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.print-instructions')).toBeVisible();
  await expect(page.locator('.result-screen')).toBeHidden();
  await expect(page.locator('.print-instructions > article')).toHaveCount(2);
  await expect(page.locator('.print-instructions > article ol > li')).toHaveCount(10);
  await expect(page.locator('.print-instructions')).toContainText('ДЕМО-multiple-boxes');
  await expect(page.locator('.print-instructions')).toContainText('box-m:1');
  await expect(page.locator('.print-instructions')).toContainText('box-m:2');
});

test('demo catalog creates, persists, updates and deletes boxes including zero stock', async ({
  page,
}) => {
  await page.goto('/?mode=demo');
  await page.getByRole('button', { name: 'Каталог коробок', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить коробку' }).click();
  const editor = page.locator('.catalog-editor');
  await editor.getByRole('button', { name: 'Сохранить коробку' }).click();
  await expect(editor.getByLabel(/^Название/)).toHaveAttribute('aria-invalid', 'true');
  await editor.getByLabel(/^Название/).fill('Коробка E2E');
  await editor.getByLabel(/^Код коробки/).fill('e2e-box');
  await editor.getByLabel(/^Длина, мм/).fill('350');
  await editor.getByLabel(/^Ширина, мм/).fill('250');
  await editor.getByLabel(/^Высота, мм/).fill('150');
  await editor.getByLabel(/^Максимальный вес, г/).fill('6000');
  await editor.getByLabel(/^В наличии, шт\./).fill('0');
  await editor.getByRole('button', { name: 'Сохранить коробку' }).click();
  await expect(editor).toBeHidden();
  const card = page
    .locator('.catalog-card')
    .filter({ has: page.getByRole('heading', { name: 'Коробка E2E', exact: true }) });
  await expect(card).toContainText('Нет в наличии');
  await page.reload();
  await page.getByRole('button', { name: 'Каталог коробок', exact: true }).click();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Изменить коробку Коробка E2E', exact: true }).click();
  await expect(editor.getByLabel(/^Код коробки/)).toHaveAttribute('readonly', '');
  await editor.getByLabel(/^В наличии, шт\./).fill('2');
  await editor.getByRole('button', { name: 'Сохранить коробку' }).click();
  await expect(card).toContainText('2 шт. в наличии');
  await card.getByRole('button', { name: 'Удалить коробку Коробка E2E', exact: true }).click();
  await card.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Удалить коробку Коробка E2E', exact: true }).click();
  await card.getByRole('button', { name: 'Да, удалить', exact: true }).click();
  await expect(card).toHaveCount(0);
  const saved = await page.evaluate(
    () => JSON.parse(localStorage.getItem('duncarbox.demo.catalog.v1') ?? '[]') as BoxType[],
  );
  expect(saved.some((box) => box.id === 'e2e-box')).toBe(false);
});

test('order rows duplicate with stable IDs, add with focus and reject fractional dimensions', async ({
  page,
}) => {
  await loadOrder(page, 'simple-order');
  const originalId = await page
    .getByLabel('Название товара 1', { exact: true })
    .getAttribute('data-product-id');
  await page.getByRole('button', { name: 'Дублировать товар 1', exact: true }).click();
  const duplicateId = await page
    .getByLabel('Название товара 2', { exact: true })
    .getAttribute('data-product-id');
  expect(duplicateId).not.toBe(originalId);
  await page.getByRole('button', { name: 'Удалить товар 1', exact: true }).click();
  await expect(page.getByLabel('Название товара 1', { exact: true })).toHaveAttribute(
    'data-product-id',
    duplicateId!,
  );
  await page.getByRole('button', { name: 'Добавить товар', exact: false }).click();
  await expect(page.getByLabel('Название товара 2', { exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Рассчитать упаковку' }).click();
  await expect(page.getByLabel('Название товара 2', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await expect(page.getByLabel('Название товара 2', { exact: true })).toBeFocused();
  await page.getByLabel('Длина товара 1, мм', { exact: true }).fill('100.5');
  await page.getByRole('button', { name: 'Рассчитать упаковку' }).click();
  await expect(page.getByLabel('Длина товара 1, мм', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await expect(page.locator('.error-notice')).toContainText('Введите целое число.');
  await expect(page.getByRole('heading', { name: 'План упаковки', exact: true })).toHaveCount(0);
});

test('an edited demo gives a useful error, reload recovers, later edits mark the saved plan stale', async ({
  page,
}) => {
  await loadOrder(page, 'simple-order');
  await page.getByLabel('Длина товара 1, мм', { exact: true }).fill('101');
  await page.getByRole('button', { name: 'Рассчитать упаковку' }).click();
  await expect(page.locator('.error-notice')).toContainText(
    'Демонстрационный режим воспроизводит только готовые сценарии',
  );
  await page.getByRole('button', { name: 'Загрузить демо-заказ заново' }).click();
  await expect(page.getByLabel('Длина товара 1, мм', { exact: true })).toHaveValue('100');
  await calculate(page);
  await page
    .getByRole('navigation', { name: 'Основные разделы' })
    .getByRole('button', { name: '01 Заказ' })
    .click();
  await page.getByLabel('Кол-во товара 1, шт.', { exact: true }).fill('3');
  await page
    .getByRole('navigation', { name: 'Основные разделы' })
    .getByRole('button', { name: /План упаковки/ })
    .click();
  await expect(page.getByText('Данные заказа изменились.', { exact: true })).toBeVisible();
  const exported = await jsonExport(page);
  expect(exported.request.products[0].quantity).toBe(2);
  expect(exported.result.metrics.packed_items).toBe(2);
});

test('trimming product names does not mark a just-calculated plan stale', async ({ page }) => {
  await loadOrder(page, 'simple-order');
  await page
    .getByLabel('Название товара 1', { exact: true })
    .fill(`  ${simpleRequest.products[0].name}  `);
  await calculate(page);
  await expect(page.getByText('Данные заказа изменились.', { exact: true })).toHaveCount(0);
  const exported = await jsonExport(page);
  expect(exported.request.products[0].name).toBe(simpleRequest.products[0].name);
});

for (const scenario of [
  { id: 'oversized', status: 'Невозможно упаковать заказ', unpacked: 1, boxes: 0 },
  { id: 'stock-shortage', status: 'Упакован частично', unpacked: 2, boxes: 1 },
]) {
  test(`${scenario.id}: failed items and diagnostic reasons remain visible and printable`, async ({
    page,
  }) => {
    await loadOrder(page, scenario.id);
    await calculate(page);
    await expect(page.locator('.status-badge')).toContainText(scenario.status);
    await expect(page.getByRole('heading', { name: 'Осталось без упаковки' })).toBeVisible();
    await expect(page.locator('.unpacked-list > li')).toHaveCount(scenario.unpacked);
    await expect(page.locator('.box-selector > button')).toHaveCount(scenario.boxes);
    await expect(page.getByRole('region', { name: 'Причины и пояснения' })).toBeVisible();
    const exported = await jsonExport(page);
    expect(exported.result.unpacked_items).toHaveLength(scenario.unpacked);
    await page.emulateMedia({ media: 'print' });
    await expect(page.locator('.print-instructions')).toBeVisible();
    await expect(page.locator('.print-instructions')).toContainText('Не упаковано');
    await expect(page.locator('.print-instructions')).toContainText('Причины и пояснения');
  });
}

test('API validation details appear on the field, submission recovers and only one request runs', async ({
  page,
}) => {
  let calls = 0;
  let submitted: PackingRequest | undefined;
  await mockApi(page, async (route) => {
    calls += 1;
    submitted = route.request().postDataJSON() as PackingRequest;
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (calls === 1)
      return route.fulfill({
        status: 422,
        json: {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Запрос не прошёл проверку.',
            details: [
              {
                field: 'body.products.0.length',
                message: 'Input should be greater than 0',
                type: 'greater_than',
              },
            ],
          },
        },
      });
    return route.fulfill({ json: simpleResult });
  });
  await loadOrder(page, 'simple-order', 'api');
  await page.getByRole('button', { name: 'Рассчитать упаковку' }).click();
  await expect(page.getByLabel('Длина товара 1, мм', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await expect(page.locator('.product-table')).toContainText('Значение должно быть больше нуля.');
  expect(calls).toBe(1);
  await page.getByLabel('Длина товара 1, мм', { exact: true }).fill('99');
  await page.getByLabel('Длина товара 1, мм', { exact: true }).fill('100');
  await calculate(page);
  expect(calls).toBe(2);
  expect(submitted?.boxes).toEqual(simpleRequest.boxes);
  expect(submitted?.products).toEqual(simpleRequest.products);
  await expect(page.getByLabel('Длина товара 1, мм', { exact: true })).toHaveCount(0);
  await expect(page.locator('.status-badge')).toContainText('Заказ упакован');
});

test('a failed scenario download retries that download before calculation', async ({ page }) => {
  let scenarioCalls = 0;
  let packingCalls = 0;
  await mockApi(page, async (route) => {
    packingCalls += 1;
    await route.fulfill({ json: simpleResult });
  });
  await page.route('**/api/v1/demo/scenarios/simple-order', async (route) => {
    scenarioCalls += 1;
    if (scenarioCalls === 1)
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: 'HTTP_ERROR',
            message: 'Не удалось загрузить демонстрационный заказ.',
            details: [],
          },
        },
      });
    return route.fulfill({ json: simpleRequest });
  });
  await page.goto('/?mode=api');
  await expect(page.getByLabel('Демо-сценарий')).toBeEnabled();
  await page.getByLabel('Демо-сценарий').selectOption('simple-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ' }).click();
  await expect(page.locator('.error-notice')).toContainText(
    'Не удалось загрузить демонстрационный заказ.',
  );
  await page.getByRole('button', { name: /Повторить попытку/ }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-simple-order');
  expect(scenarioCalls).toBe(2);
  expect(packingCalls).toBe(0);
  await calculate(page);
  expect(packingCalls).toBe(1);
});

test('choosing an API alternative resets the step and exports the selected complete plan', async ({
  page,
}) => {
  const result = structuredClone(multipleResult);
  result.algorithm_version = 'test-engine-v1';
  result.issues = result.issues.filter((issue) => issue.code !== 'DEMO_STUB');
  const alternative: PackingAlternative = {
    id: 'reverse-box-order',
    description: 'Другой порядок коробок',
    status: result.status,
    metrics: structuredClone(result.metrics),
    packed_boxes: structuredClone(result.packed_boxes).reverse(),
    unpacked_items: [],
    issues: [],
  };
  result.alternatives = [alternative];
  await mockApi(page, (route) => route.fulfill({ json: result }));
  await loadOrder(page, 'multiple-boxes', 'api');
  await calculate(page);
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  await page.locator('.alternatives summary').click();
  await page.getByRole('button', { name: /Другой порядок коробок/ }).click();
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  await expect(page.getByRole('button', { name: /Другой порядок коробок/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  const exported = await jsonExport(page);
  expect(exported.selected_plan_id).toBe(alternative.id);
  expect(exported.selected_plan.packed_boxes[0].id).toBe('box-m:2');
  expect(exported.selected_plan.packed_boxes).toHaveLength(2);
  await page.getByRole('button', { name: /Рекомендуемый/ }).click();
  await expect(page.locator('.step-counter')).toHaveText('0 / 4');
  await expect(page.locator('.print-instructions > article').first()).toContainText('box-m:1');
});

test('WebGL failure keeps instructions usable through keyboard-accessible layers', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      context: string,
      ...args: unknown[]
    ) {
      if (context === 'webgl' || context === 'webgl2' || context === 'experimental-webgl')
        return null;
      return Reflect.apply(original, this, [context, ...args]);
    } as typeof original;
  });
  await loadOrder(page, 'simple-order');
  await calculate(page);
  await expect(page.getByText('3D недоступен в этом браузере.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: '3D', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  const item = page.locator('.viewer-layer svg [role="button"]').first();
  await item.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.viewer-inspection')).toContainText(simpleRequest.products[0].name);
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(2);
});

test('tablet order and result fit the viewport while the input table scrolls locally', async ({
  page,
}) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await loadOrder(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await calculate(page);
  await expect(page.locator('.packing-viewer')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await expect(page.getByRole('button', { name: 'Следующий шаг →', exact: true })).toBeVisible();
});
