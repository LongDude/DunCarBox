import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = (name: string) => JSON.parse(readFileSync(
  new URL(`../src/features/demo/fixture-data/${name}.json`, import.meta.url), 'utf8',
));

test('background progress, duration, alternatives help and sorted cartons', async ({ page }, testInfo) => {
  const id = 'b'.repeat(32);
  let completed = false;
  const result = fixture('multiple-boxes.response');
  result.calculation_seconds = 12.345;
  result.packed_boxes.reverse();
  result.packed_boxes[0].fill_ratio = 0.2;
  result.packed_boxes[1].fill_ratio = 0.8;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/health')) return route.fulfill({ json: { status: 'ok', api_version: 'v1', engine: 'candidate-packing-v1' } });
    if (path.endsWith('/boxes')) return route.fulfill({ json: fixture('catalog.boxes') });
    if (path.endsWith('/demo/scenarios')) return route.fulfill({ json: fixture('scenarios') });
    if (path.endsWith('/demo/scenarios/multiple-boxes')) return route.fulfill({ json: fixture('multiple-boxes.request') });
    if (path.endsWith('/result')) return route.fulfill({ json: result });
    if (path.includes('/pack/jobs')) return route.fulfill({ json: {
      id, status: completed ? 'completed' : 'running', error: null, elapsed_seconds: 5,
      timeout_seconds: null, stage: completed ? 'completed' : 'heuristic', progress: completed ? 1 : 0.5,
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/?mode=api');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('z3');
  await expect(page.getByLabel('Предложить альтернативы')).toBeDisabled();
  await expect(page.locator('#alternatives-help')).toContainText('один лучший найденный план');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('heuristic');
  await page.getByLabel('Параллельные процессы', { exact: true }).fill('24');
  await expect(page.locator('#solver-workers-hint')).toContainText('до 12 процессов');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-multiple-boxes');
  const submitted = page.waitForRequest(request => request.url().endsWith('/pack/jobs'));
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  expect((await submitted).postDataJSON().options.solver_workers).toBe(24);
  await expect(page.getByRole('progressbar')).toHaveAttribute('value', '0.5');
  await expect(page.locator('.calculation-progress')).toContainText('50% этапа');
  await page.screenshot({ path: testInfo.outputPath('calculation-progress.png'), fullPage: true });
  completed = true;
  await expect(page.locator('.result-screen h1')).toBeVisible();
  await expect(page.getByText('Время построения плана: 12,345 с')).toBeVisible();
  const widths = await page.locator('.box-selector .fill-track > i').evaluateAll(elements =>
    elements.map(element => Number.parseFloat((element as HTMLElement).style.width)),
  );
  expect(widths).toEqual([80, 20]);
  await page.screenshot({ path: testInfo.outputPath('calculation-result.png'), fullPage: true });
});
