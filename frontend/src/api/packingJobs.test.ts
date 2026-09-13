import { afterEach, expect, it, vi } from 'vitest';
import { packingApi } from './packing';
import { demoFixtures } from '../features/demo/fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const id = 'a'.repeat(32);
const job = { id, status: 'running', error: null, elapsed_seconds: 0, timeout_seconds: null };
const fixture = demoFixtures['simple-order'];
const large = () => ({ ...fixture.request, products: [{ ...fixture.request.products[0], quantity: 10_000 }] });

it.each([2, 10_000])('calculates %i units through jobs and accepts a result after 120 seconds', async (quantity) => {
  vi.useFakeTimers();
  let polls = 0;
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith('/result')) return Response.json(fixture.response);
    if (url.endsWith('/jobs')) return Response.json(job, { status: 202 });
    return Response.json({ ...job, status: ++polls < 125 ? 'running' : 'completed' });
  });
  vi.stubGlobal('fetch', fetchMock);
  const request = { ...fixture.request, products: [{ ...fixture.request.products[0], quantity }] };
  const promise = packingApi.pack(request);
  await vi.advanceTimersByTimeAsync(125_000);
  await expect(promise).resolves.toEqual(fixture.response);
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/pack/jobs');
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/pack')).toBe(false);
});

it('reports server progress through completion', async () => {
  vi.useFakeTimers();
  const progress = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/result')) return Response.json(fixture.response);
    return Response.json({ ...job, stage: url.endsWith('/jobs') ? 'solver' : 'completed',
      progress: url.endsWith('/jobs') ? 0.4 : 1, status: url.endsWith('/jobs') ? 'running' : 'completed' });
  }));
  const pending = packingApi.pack(fixture.request, undefined, progress);
  await vi.advanceTimersByTimeAsync(1_000);
  await pending;
  expect(progress.mock.calls.map(([value]) => [value.stage, value.progress])).toEqual([['solver', 0.4], ['completed', 1]]);
});

it('uses background transport for an unlimited Z3 search with 16 processes on a small order', async () => {
  const fetchMock = vi.fn(async (url: string) => Response.json(url.endsWith('/result') ? fixture.response : { ...job, status: 'completed' }));
  vi.stubGlobal('fetch', fetchMock);
  const request = { ...fixture.request, options: { algorithm: 'z3' as const, solver_workers: 16 } };
  await packingApi.pack(request);
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/pack/jobs', expect.objectContaining({ body: JSON.stringify(request) }));
});

it('cancels the server job even when cancellation arrives before the creation response', async () => {
  const controller = new AbortController();
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === 'DELETE') return new Response(null, { status: 204 });
    controller.abort();
    return Response.json(job);
  });
  vi.stubGlobal('fetch', fetchMock);
  await expect(packingApi.pack(large(), controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  expect(fetchMock).toHaveBeenCalledWith(`/api/v1/pack/jobs/${id}`, expect.objectContaining({ method: 'DELETE', signal: expect.any(AbortSignal) }));
});

it('shows job failure instead of rendering a false plan', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => options.method === 'DELETE'
    ? new Response(null, { status: 204 }) : Response.json({ ...job, status: 'failed', error: 'Ошибка расчёта.' })));
  await expect(packingApi.pack(large())).rejects.toMatchObject({ code: 'PACKING_JOB_FAILED', message: 'Ошибка расчёта.' });
});
