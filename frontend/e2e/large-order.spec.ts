import { expect, test } from '@playwright/test';
import type { PackingResult } from '../src/types/packing';

test.skip(!process.env.DUNCARBOX_LIVE_E2E, 'Requires real API and PostgreSQL');
test.use({ actionTimeout: 15_000 });

test('menu demo: 10000 items, 100 products, 8 box types and cancellable calculation', async ({ page, request }) => {
  await page.goto('/?mode=api');
  await page.getByLabel('Демо-сценарий').selectOption('large-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-large-order');
  await expect(page.getByLabel('Кол-во товара 1, шт.', { exact: true })).toHaveValue('100');
  await expect(page.getByText('10000 шт.', { exact: true }).first()).toBeVisible();
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('z3');
  await expect(page.getByLabel('Лимит поиска, с', { exact: true })).toHaveCount(0);
  await page.getByLabel('Параллельные процессы', { exact: true }).fill('16');
  const started = page.waitForResponse(r => r.url().endsWith('/pack/jobs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  const response = await started;
  expect(response.status()).toBe(202);
  const payload = response.request().postDataJSON();
  expect(payload.products).toHaveLength(100);
  expect(payload.boxes).toHaveLength(8);
  expect(payload.options).toMatchObject({ algorithm: 'z3', solver_workers: 16 });
  expect(payload.options).not.toHaveProperty('solver_timeout_ms');
  const job = await response.json();
  const cancelled = page.waitForResponse(r => r.url().endsWith(`/pack/jobs/${job.id}`) && r.request().method() === 'DELETE');
  await page.getByRole('button', { name: 'Отменить расчёт', exact: true }).click();
  expect((await cancelled).status()).toBe(204);
  expect((await (await request.get(`/api/v1/pack/jobs/${job.id}`)).json()).status).toBe('cancelled');
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-large-order');
});

test('large menu demo: full real calculation and navigation through every box', async ({ page, request }) => {
  test.skip(!process.env.DUNCARBOX_LARGE_DEMO_E2E, 'Enable the full calculation explicitly in CI');
  test.setTimeout(1_800_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const algorithm = process.env.DUNCARBOX_DEMO_ALGORITHM || 'heuristic';
  await page.goto('/?mode=api');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption(algorithm);
  await page.getByLabel('Демо-сценарий').selectOption('large-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-large-order');
  const resultResponse = page.waitForResponse(r => /\/pack\/jobs\/[^/]+\/result$/.test(r.url()), { timeout: 1_700_000 });
  const started = Date.now();
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  await expect(page.getByText(/Фоновый расчёт/)).toBeVisible();
  const result = await (await resultResponse).json() as PackingResult;
  expect(result.status).toBe('success');
  expect(result.metrics.total_items).toBe(10000);
  expect(result.metrics.packed_items).toBe(10000);
  const placements = result.packed_boxes.flatMap(box => box.placements);
  expect(placements).toHaveLength(10000);
  expect(new Set(placements.map(p => p.item_instance_id)).size).toBe(10000);
  expect(new Set(placements.map(p => p.product_id)).size).toBe(100);
  for (const box of result.packed_boxes) {
    expect(box.instructions).toHaveLength(box.placements.length + 2);
    for (const placement of box.placements) expect(box.instructions[placement.step]).toMatchObject(placement);
  }
  console.log(`Large demo ${algorithm}: ${JSON.stringify({ elapsed_seconds: (Date.now() - started) / 1000, metrics: result.metrics, optimization: result.optimization })}`);
  await expect(page.locator('.result-screen h1')).toBeVisible();
  await expect(page.locator('.packing-viewer canvas')).toBeVisible();
  expect(await page.locator('.box-card').count()).toBeLessThanOrEqual(12);
  await expect(page.locator('.print-instructions')).toHaveCount(0);
  await page.getByLabel('Номер коробки', { exact: true }).selectOption(String(result.packed_boxes.length - 1));
  await expect(page.getByLabel('Номер коробки', { exact: true })).toHaveValue(String(result.packed_boxes.length - 1));
  await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
  await expect(page.locator('.step-counter')).toContainText('1 /');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await request.get('/api/v1/health')).ok()).toBe(true);
  expect(errors).toEqual([]);
});
