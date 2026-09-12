import { ApiError, apiRequest } from './client';
import { checkedResponse, responseGuards } from './responseValidation';
import { isRecord } from './validation';
import type { PackingRequest, PackingResult } from '../types/packing';

interface Job {
  id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  error: string | null;
  elapsed_seconds: number;
  timeout_seconds: number | null;
}

function isJob(value: unknown): boolean {
  return isRecord(value) && typeof value.id === 'string' && /^[a-f0-9]{32}$/.test(value.id)
    && ['running', 'completed', 'failed', 'cancelled'].includes(String(value.status))
    && (value.error === null || typeof value.error === 'string')
    && typeof value.elapsed_seconds === 'number' && value.elapsed_seconds >= 0
    && (value.timeout_seconds === null || (typeof value.timeout_seconds === 'number' && Number.isFinite(value.timeout_seconds) && value.timeout_seconds > 0));
}

function pause(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, 1_000);
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
  });
}

export async function packInBackground(request: PackingRequest, signal?: AbortSignal): Promise<PackingResult> {
  signal?.throwIfAborted();
  let job: Job | undefined;
  let completed = false;
  try {
    // Receive the job ID even if Cancel is clicked while POST is in flight,
    // so that we can also stop the server worker in finally.
    job = await checkedResponse(apiRequest<Job>('/pack/jobs', {
      method: 'POST', body: JSON.stringify(request),
    }), isJob);
    const deadline = job.timeout_seconds === null ? Infinity : Date.now() + (job.timeout_seconds + 15) * 1_000;
    while (true) {
      signal?.throwIfAborted();
      if (job.status === 'completed') {
        const result = await checkedResponse(apiRequest<PackingResult>(`/pack/jobs/${job.id}/result`, { signal }, 120_000), responseGuards.result);
        completed = true;
        return result;
      }
      if (job.status === 'failed' || job.status === 'cancelled') {
        throw new ApiError(job.error ?? 'Расчёт отменён. Запустите его заново.', 'PACKING_JOB_FAILED');
      }
      if (Date.now() >= deadline) throw new ApiError('Превышено время ожидания фонового расчёта.', 'TIMEOUT');
      await pause(signal);
      job = await checkedResponse(apiRequest<Job>(`/pack/jobs/${job.id}`, { signal }), isJob);
    }
  } finally {
    if (job && !completed) {
      // A separate request is necessary: the caller's signal may already be aborted.
      void apiRequest<void>(`/pack/jobs/${job.id}`, { method: 'DELETE' }).catch(() => undefined);
    }
  }
}
