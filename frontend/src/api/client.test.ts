import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from './client';
import { createDataSource } from './dataSource';
import { demoFixtures } from '../features/demo/fixtures';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('live API boundary', () => {
  it('sends the exact snapshot through the live adapter', async () => {
    const fixture = demoFixtures['simple-order'];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(fixture.response), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await createDataSource('api').pack(fixture.request)).toEqual(fixture.response);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/pack', expect.objectContaining({
      method: 'POST', body: JSON.stringify(fixture.request), signal: expect.any(AbortSignal),
    }));
  });

  it('preserves server diagnostics and field details', async () => {
    const error = { code: 'VALIDATION_ERROR', message: 'Запрос не прошёл проверку.', details: [{ field: 'body.products.0.length', message: 'Input should be greater than 0', type: 'greater_than' }] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error }), { status: 422 })));
    await expect(apiRequest('/pack')).rejects.toMatchObject({ ...error, status: 422 });
  });

  it.each(['<html>Proxy unavailable</html>', 'null', 'true', '{}'])('rejects malformed successful response %s', async (body) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })));
    await expect(createDataSource('api').health()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });

  it('rejects malformed nested packing results before rendering', async () => {
    const result = structuredClone(demoFixtures['simple-order'].response);
    Reflect.deleteProperty(result.packed_boxes[0].placements[0], 'position');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(result), { status: 200 })));
    await expect(createDataSource('api').pack(demoFixtures['simple-order'].request)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });

  it('handles unavailable proxies and network failures with safe messages', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>internal proxy path</html>', { status: 502 })));
    await expect(apiRequest('/health')).rejects.toMatchObject({ code: 'HTTP_ERROR', status: 502 });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('private network detail'); }));
    await expect(apiRequest('/health')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });

  it('returns no body for a successful delete', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })));
    await expect(createDataSource('api').boxes.remove('box-s')).resolves.toBeUndefined();
  });

  it('cancels with the caller signal and distinguishes a request timeout', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const controller = new AbortController();
    const cancelled = apiRequest('/health', { signal: controller.signal });
    const cancelledAssertion = expect(cancelled).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await cancelledAssertion;
    const timeout = apiRequest('/health');
    const timeoutAssertion = expect(timeout).rejects.toMatchObject({ code: 'TIMEOUT' });
    await vi.advanceTimersByTimeAsync(15_000);
    await timeoutAssertion;
  });

  it('allows a packing calculation to finish after the catalog request timeout', async () => {
    vi.useFakeTimers();
    const response = demoFixtures['simple-order'].response;
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      setTimeout(() => resolve(new Response(JSON.stringify(response))), 20_000);
    })));
    const pending = createDataSource('api').pack(demoFixtures['simple-order'].request);
    await vi.advanceTimersByTimeAsync(20_000);
    await expect(pending).resolves.toEqual(response);
  });
});
