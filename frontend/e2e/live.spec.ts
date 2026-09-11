import { expect, test } from '@playwright/test';
import type { PackingResult } from '../src/types/packing';

test.skip(!process.env.DUNCARBOX_LIVE_E2E, 'Requires real API and PostgreSQL');

for (const [scenario, status, count] of [
  ['simple-order', 'success', 2],
  ['multiple-boxes', 'success', 6],
  ['oversized', 'impossible', 0],
  ['stock-shortage', 'partial', 1],
] as const) {
  test(`live API: ${scenario}, server instructions and placements`, async ({ page, request }) => {
    const health = await request.get('/api/v1/health');
    expect((await health.json()).engine).toBe('candidate-packing-v1');
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/?mode=api');
    await page.getByLabel('Демо-сценарий').selectOption(scenario);
    await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
    await expect(page.getByLabel('Номер заказа')).toHaveValue(`ДЕМО-${scenario}`);
    const response = page.waitForResponse(r => r.url().endsWith('/api/v1/pack') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
    const result = await (await response).json() as PackingResult;
    expect(result.status).toBe(status);
    expect(result.metrics.packed_items).toBe(count);
    expect(result.algorithm_version).toBe('candidate-packing-v1');
    expect(result.issues.some(issue => issue.code === 'DEMO_STUB')).toBe(false);
    await expect(page.getByRole('heading', { name: 'План упаковки', exact: true })).toBeVisible();
    for (const plan of [result, ...result.alternatives]) {
      for (const box of plan.packed_boxes) {
        expect(box.instructions).toHaveLength(box.placements.length + 2);
        for (const placement of box.placements) {
          expect(box.instructions[placement.step]).toMatchObject(placement);
        }
      }
    }
    if (count) {
      await expect(page.locator('.packing-viewer canvas')).toBeVisible();
      await page.getByRole('button', { name: 'Следующий шаг →', exact: true }).click();
      await expect(page.locator('.step-counter')).toContainText('1 /');
      await page.getByRole('button', { name: 'По слоям', exact: true }).click();
      await expect(page.locator('.viewer-layer svg [role="button"]')).toHaveCount(1);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('live API: changed quantity calculates a new plan', async ({ page }) => {
  await page.goto('/?mode=api');
  await page.getByLabel('Демо-сценарий').selectOption('simple-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-simple-order');
  await page.getByLabel('Кол-во товара 1, шт.').fill('3');
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/pack'));
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  const result = await (await response).json() as PackingResult;
  expect(result.status).toBe('success');
  expect(result.metrics.packed_items).toBe(3);
  await expect(page.locator('.status-badge')).toContainText('Заказ упакован');
});

test('live PostgreSQL catalog: create, reload, update and delete', async ({ page, request }) => {
  const id = `live-e2e-${Date.now()}`;
  try {
    await page.goto('/?mode=api');
    await page.getByRole('button', { name: 'Каталог коробок', exact: true }).click();
    await page.getByRole('button', { name: 'Добавить коробку', exact: true }).click();
    const editor = page.locator('.catalog-editor');
    for (const [label, value] of [
      ['Название', 'Проверка PostgreSQL'], ['Код коробки', id], ['Длина, мм', '350'],
      ['Ширина, мм', '250'], ['Высота, мм', '150'], ['Максимальный вес, г', '6000'],
      ['В наличии, шт.', '0'],
    ]) await editor.getByLabel(label, { exact: false }).fill(value);
    const created = page.waitForResponse(r => r.url().endsWith('/api/v1/boxes') && r.request().method() === 'POST');
    await editor.getByRole('button', { name: 'Сохранить коробку' }).click();
    expect((await created).status()).toBe(201);
    await page.reload();
    await page.getByRole('button', { name: 'Каталог коробок', exact: true }).click();
    const row = page.locator('.catalog-card').filter({ hasText: id });
    await expect(row).toContainText('Проверка PostgreSQL');
    await row.getByRole('button', { name: /Изменить/ }).click();
    await editor.getByLabel(/^В наличии/).fill('7');
    const updated = page.waitForResponse(r => r.url().endsWith(`/api/v1/boxes/${id}`) && r.request().method() === 'PUT');
    await editor.getByRole('button', { name: 'Сохранить коробку' }).click();
    expect((await updated).status()).toBe(200);
    const catalog = await (await request.get('/api/v1/boxes')).json();
    expect(catalog.find((box: {id: string}) => box.id === id).available_count).toBe(7);
    await row.getByRole('button', { name: /Удалить/ }).click();
    await row.getByRole('button', { name: 'Да, удалить', exact: true }).click();
    await expect(row).toHaveCount(0);
  } finally {
    await request.delete(`/api/v1/boxes/${id}`);
  }
});
