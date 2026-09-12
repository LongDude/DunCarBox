import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { demoCatalog, demoFixtures, demoScenarios } from '../features/demo/fixtures';
import { createDataSource, DEMO_CATALOG_STORAGE_KEY } from './dataSource';

const source = createDataSource('demo');

beforeEach(() => {
  const storage = new Map([[DEMO_CATALOG_STORAGE_KEY, JSON.stringify(demoCatalog)]]);
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('interchangeable data source', () => {
  it.each(demoScenarios)('reproduces canonical $id result including diagnostic markers', async (scenario) => {
    const input = await source.scenario(scenario.id);
    expect(await source.pack(input)).toEqual(demoFixtures[scenario.id].response);
  });

  it('matches independently of rows, object key order and outer name whitespace', async () => {
    const input = await source.scenario('multiple-boxes');
    input.products.reverse();
    input.products = input.products.map((product) => Object.fromEntries(Object.entries(product).reverse()) as typeof product);
    input.products[0].name = ` ${input.products[0].name} `;
    expect(await source.pack(input)).toEqual(demoFixtures['multiple-boxes'].response);
    const shortage = await source.scenario('stock-shortage');
    shortage.boxes.reverse();
    expect(await source.pack(shortage)).toEqual(demoFixtures['stock-shortage'].response);
  });

  it('honors options and never mutates shared fixtures', async () => {
    const input = await source.scenario('simple-order');
    input.options = { include_alternatives: false };
    expect((await source.pack(input)).alternatives).toEqual([]);
    input.options = { max_alternatives: 0 };
    expect((await source.pack(input)).alternatives).toEqual([]);
    input.options = { max_alternatives: 1 };
    const result = await source.pack(input);
    expect(result.alternatives).toEqual(demoFixtures['simple-order'].response.alternatives.slice(0, 1));
    result.packed_boxes[0].name = 'mutated';
    expect((await source.pack(demoFixtures['simple-order'].request)).packed_boxes[0].name).not.toBe('mutated');
  });

  it('refuses edited input instead of fabricating a calculation', async () => {
    const input = await source.scenario('simple-order');
    input.products[0].length += 1;
    await expect(source.pack(input)).rejects.toMatchObject({ code: 'ENGINE_NOT_IMPLEMENTED', status: 503 });
    input.products[0].length = 0;
    await expect(source.pack(input)).rejects.toMatchObject({ code: 'VALIDATION_ERROR', status: 422 });
  });

  it('refuses Z3 in offline demo instead of presenting a fixture as an optimized result', async () => {
    const input = await source.scenario('simple-order');
    input.options = { algorithm: 'z3', solver_timeout_ms: 1000, solver_workers: 1 };
    await expect(source.pack(input)).rejects.toMatchObject({ code: 'ENGINE_NOT_IMPLEMENTED', message: expect.stringContaining('Z3 работает только на сервере') });
  });

  it('persists demo CRUD, reports conflicts and keeps scenario stocks independent', async () => {
    const box = { ...demoCatalog[0], id: 'operator-box', name: ' Коробка оператора ' };
    expect((await source.boxes.create(box)).name).toBe('Коробка оператора');
    await expect(source.boxes.create(box)).rejects.toMatchObject({ code: 'CONFLICT' });
    await source.boxes.update({ ...box, available_count: 0 });
    expect((await createDataSource('demo').boxes.list()).find((entry) => entry.id === box.id)?.available_count).toBe(0);
    await source.boxes.remove(box.id);
    await expect(source.boxes.update(box)).rejects.toMatchObject({ code: 'NOT_FOUND' });
    await expect(source.boxes.remove(box.id)).rejects.toMatchObject({ code: 'NOT_FOUND' });
    const existing = (await source.boxes.list())[0];
    await source.boxes.update({ ...existing, available_count: 0 });
    expect(await source.scenario('simple-order')).toEqual(demoFixtures['simple-order'].request);
  });

  it('keeps editing usable when persistence is blocked', async () => {
    await source.boxes.list();
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } });
    const box = { ...demoCatalog[0], id: 'memory-only' };
    await source.boxes.create(box);
    expect((await source.boxes.list()).some((entry) => entry.id === box.id)).toBe(true);
    await source.boxes.remove(box.id);
  });

  it('supports cancellation before and during the async operation', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(source.scenarios(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    const pending = new AbortController();
    const promise = source.scenario('simple-order', pending.signal);
    pending.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('rejects inherited object keys as scenario IDs', async () => {
    await expect(source.scenario('constructor')).rejects.toMatchObject({ code: 'NOT_FOUND' });
  });
});
