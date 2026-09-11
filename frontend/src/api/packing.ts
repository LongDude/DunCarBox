import { apiRequest } from './client';
import { checkedResponse, responseGuards } from './responseValidation';
import { assertValid, validateBox, validateRequest } from './validation';
import type { BoxType, DemoScenario, HealthResponse, PackingRequest, PackingResult } from '../types/packing';

export const packingApi = {
  health: (signal?: AbortSignal) => checkedResponse(apiRequest<HealthResponse>('/health', { signal }), responseGuards.health),
  scenarios: (signal?: AbortSignal) => checkedResponse(apiRequest<DemoScenario[]>('/demo/scenarios', { signal }), responseGuards.scenarios),
  scenario: (id: string, signal?: AbortSignal) =>
    checkedResponse(apiRequest<PackingRequest>(`/demo/scenarios/${encodeURIComponent(id)}`, { signal }), responseGuards.request),
  pack: async (request: PackingRequest, signal?: AbortSignal) => {
    assertValid(validateRequest(request));
    return checkedResponse(apiRequest<PackingResult>('/pack', { method: 'POST', body: JSON.stringify(request), signal }), responseGuards.result);
  },
};

export const boxesApi = {
  list: (signal?: AbortSignal) => checkedResponse(apiRequest<BoxType[]>('/boxes', { signal }), responseGuards.boxes),
  create: async (box: BoxType) => {
    assertValid(validateBox(box));
    return checkedResponse(apiRequest<BoxType>('/boxes', { method: 'POST', body: JSON.stringify(box) }), responseGuards.box);
  },
  update: async (box: BoxType) => {
    assertValid(validateBox(box));
    return checkedResponse(apiRequest<BoxType>(`/boxes/${encodeURIComponent(box.id)}`, {
      method: 'PUT', body: JSON.stringify(box),
    }), responseGuards.box);
  },
  remove: (id: string) => apiRequest<void>(`/boxes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
