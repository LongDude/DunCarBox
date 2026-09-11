import { useCallback, useEffect, useState } from 'react';
import { toApiError } from './client';
import type { ApiError } from './client';

export type RemoteData<T> =
  | { status: 'idle' | 'loading' }
  | { status: 'error'; error: ApiError }
  | { status: 'success'; data: T };

/** The loader must be stable (module function or useCallback). */
export function useRemoteData<T>(key: string | null, loader: (signal: AbortSignal) => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [stored, setStored] = useState<{ key: string | null; state: RemoteData<T> }>({
    key: null, state: { status: 'idle' },
  });
  const retry = useCallback(() => setAttempt((previous) => previous + 1), []);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    setStored({ key, state: { status: 'loading' } });
    loader(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setStored({ key, state: { status: 'success', data } });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setStored({ key, state: { status: 'error', error: toApiError(error) } });
      },
    );
    return () => controller.abort();
  }, [key, loader, attempt]);

  const state: RemoteData<T> = key === null
    ? { status: 'idle' }
    : key !== stored.key ? { status: 'loading' } : stored.state;
  return { state, retry };
}
