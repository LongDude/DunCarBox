import { afterEach, expect, it, vi } from 'vitest';
import { packingApi } from './packing';
import { demoFixtures } from '../features/demo/fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const id = 'a'.repeat(32);
const job = { id, status: 'running', error: null, elapsed_seconds: 0, timeout_seconds: null };
const fixture = demoFixtures['simple-order'];
const large = () => ({ ...fixture.request, products: [{ ...fixture.request.products[0], quantity: 10_000 }] });

it('calculates 10000 units through jobs and accepts a result after 120 seconds', async () => {
  vi.useFakeTimers();
  let polls = 0;
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith('/result')) return Response.json(fixture.response);
    if (url.endsWith('/jobs')) return Response.json(job, { status: 202 });
    return Response.json({ ...job, status: ++polls < 125 ? 'running' : 'completed' });
  });
  vi.stubGlobal('fetch', fetchMock);
  const promise = packingApi.pack(large());
  await vi.advanceTimersByTimeAsync(125_000);
  await expect(promise).resolves.toEqual(fixture.response);
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/pack/jobs');
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/pack')).toBe(false);
});

it('keeps a long search budget and 16 processes and uses background transport for a small order', async () => {
  const fetchMock = vi.fn(async (url: string) => Response.json(url.endsWith('/result') ? fixture.response : { ...job, status: 'completed' }));
  vi.stubGlobal('fetch', fetchMock);
  const request = { ...fixture.request, options: { algorithm: 'z3' as const, solver_timeout_ms: 600_000, solver_workers: 16 } };
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
