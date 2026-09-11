import { apiRequest } from './client';
import type { BoxType, DemoScenario, HealthResponse, PackingRequest, PackingResult } from '../types/packing';

export const packingApi = {
  health: (signal?: AbortSignal) => apiRequest<HealthResponse>('/health', { signal }),
  scenarios: (signal?: AbortSignal) => apiRequest<DemoScenario[]>('/demo/scenarios', { signal }),
  scenario: (id: string, signal?: AbortSignal) =>
    apiRequest<PackingRequest>(`/demo/scenarios/${encodeURIComponent(id)}`, { signal }),
  pack: (request: PackingRequest, signal?: AbortSignal) =>
    apiRequest<PackingResult>('/pack', { method: 'POST', body: JSON.stringify(request), signal }),
};

/** Catalog editing is deferred to the frontend engineer; the API is ready. */
export const boxesApi = {
  list: (signal?: AbortSignal) => apiRequest<BoxType[]>('/boxes', { signal }),
  create: (box: BoxType) => apiRequest<BoxType>('/boxes', { method: 'POST', body: JSON.stringify(box) }),
  update: (box: BoxType) => apiRequest<BoxType>(`/boxes/${encodeURIComponent(box.id)}`, {
    method: 'PUT', body: JSON.stringify(box),
  }),
  remove: (id: string) => apiRequest<void>(`/boxes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
