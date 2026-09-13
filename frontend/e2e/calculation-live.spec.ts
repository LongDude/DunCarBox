import { expect, test } from '@playwright/test';

test.skip(!process.env.DUNCARBOX_LIVE_E2E, 'Requires real API and PostgreSQL');

test('real Z3 shows unlimited search and supports manual cancellation', async ({ page, request }, testInfo) => {
  await page.goto('/?mode=api');
  await page.getByRole('combobox', { name: 'Алгоритм расчёта', exact: true }).selectOption('z3');
  await expect(page.getByLabel('Лимит поиска, с', { exact: true })).toHaveCount(0);
  await page.getByLabel('Параллельные процессы', { exact: true }).fill('2');
  await page.getByLabel('Демо-сценарий').selectOption('simple-order');
  await page.getByRole('button', { name: 'Загрузить демо-заказ', exact: true }).click();
  await expect(page.getByLabel('Номер заказа')).toHaveValue('ДЕМО-simple-order');
  await page.getByLabel('Кол-во товара 1, шт.', { exact: true }).fill('17');
  const response = page.waitForResponse(r => r.url().endsWith('/pack/jobs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Рассчитать упаковку', exact: true }).click();
  const job = await (await response).json();
  try {
    const progress = page.getByRole('progressbar', { name: 'Поиск оптимального плана Z3' });
    await expect(progress).toBeVisible();
    await expect(progress).not.toHaveAttribute('value');
    await expect(page.locator('.calculation-progress')).toContainText('без ограничения времени');
    await page.screenshot({ path: testInfo.outputPath('real-calculation-progress.png'), fullPage: true });
    const cancelled = page.waitForResponse(r => r.url().endsWith(`/pack/jobs/${job.id}`) && r.request().method() === 'DELETE');
    await page.getByRole('button', { name: 'Отменить расчёт', exact: true }).click();
    expect((await cancelled).status()).toBe(204);
    expect((await (await request.get(`/api/v1/pack/jobs/${job.id}`)).json()).status).toBe('cancelled');
    await expect(page.getByRole('button', { name: 'Рассчитать упаковку', exact: true })).toBeEnabled();
  } finally {
    await request.delete(`/api/v1/pack/jobs/${job.id}`);
  }
});
