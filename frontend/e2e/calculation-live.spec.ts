import { expect, test } from '@playwright/test';
import type { PackingResult } from '../src/types/packing';

test.skip(!process.env.DUNCARBOX_LIVE_E2E, 'Requires real API and PostgreSQL');

test('real Z3 shows budget progress and returns a timed, sorted plan', async ({ page }, testInfo) => {
  await page.goto('/?mode=api');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('z3');
  await page.getByLabel('Лимит поиска, с', { exact: true }).fill('3');
  await page.getByLabel('Параллельные процессы', { exact: true }).fill('2');
  await page.getByLabel('Демо-сценарий').selectOption('simple-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-simple-order');
  await page.getByLabel('Кол-во товара 1, шт.', { exact: true }).fill('17');
  const response = page.waitForResponse(r => r.url().endsWith('/result'));
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  await expect(page.getByRole('progressbar', { name: 'Использовано времени поиска Z3' })).toBeVisible();
  await expect(page.locator('.calculation-progress')).toContainText('бюджета времени');
  await page.screenshot({ path: testInfo.outputPath('real-calculation-progress.png'), fullPage: true });
  const result = await (await response).json() as PackingResult;
  expect(result.metrics.total_items).toBe(17);
  expect(result.metrics.packed_items + result.metrics.unpacked_items).toBe(17);
  expect(result.optimization?.reason).toBe('time_limit');
  expect(result.calculation_seconds).toBeGreaterThan(0);
  expect(result.calculation_seconds).toBeLessThan(6);
  const fills = result.packed_boxes.map(box => box.fill_ratio);
  expect(fills).toEqual([...fills].sort((a, b) => b - a));
  await expect(page.getByText(/Время построения плана:/)).toBeVisible();
  await expect(page.locator('.packing-viewer')).toBeVisible();
  await page.getByRole('button', { name: 'Показать всё', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('real-calculation-result.png'), fullPage: true });
});
