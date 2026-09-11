import type { ApiErrorDetail, ApiErrorResponse } from '../types/packing';

const API_BASE = '/api/v1';
const REQUEST_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number = 0,
    readonly details: ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  const error = value.error;
  return (
    typeof error === 'object' && error !== null &&
    'code' in error && typeof error.code === 'string' &&
    'message' in error && typeof error.message === 'string' &&
    'details' in error && Array.isArray(error.details) &&
    error.details.every((detail: unknown) => (
      typeof detail === 'object' && detail !== null &&
      'field' in detail && typeof detail.field === 'string' &&
      'message' in detail && typeof detail.message === 'string' &&
      'type' in detail && typeof detail.type === 'string'
    ))
  );
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError('Не удалось связаться с сервисом. Проверьте подключение и повторите попытку.', 'NETWORK_ERROR');
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const callerSignal = options.signal;
  callerSignal?.addEventListener('abort', abort, { once: true });
  if (callerSignal?.aborted) abort();
  let timedOut = false;
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
    if (response.status === 204) return undefined as T;

    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (isErrorResponse(body)) {
        throw new ApiError(body.error.message, body.error.code, response.status, body.error.details);
      }
      throw new ApiError('Сервис временно недоступен. Попробуйте ещё раз.', 'HTTP_ERROR', response.status);
    }
    if (body === null || typeof body !== 'object') {
      throw new ApiError('Сервис вернул некорректный ответ. Попробуйте ещё раз.', 'INVALID_RESPONSE', response.status);
    }
    return body as T;
  } catch (error: unknown) {
    if (callerSignal?.aborted) throw error;
    if (timedOut) throw new ApiError('Сервис не ответил за 15 секунд. Попробуйте ещё раз.', 'TIMEOUT');
    throw toApiError(error);
  } finally {
    globalThis.clearTimeout(timeout);
    callerSignal?.removeEventListener('abort', abort);
  }
}
