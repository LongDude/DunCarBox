import { useCallback, useEffect, useRef, useState } from 'react';
import { packingApi } from '../../api/packing';
import { toApiError } from '../../api/client';
import { useRemoteData } from '../../api/useRemoteData';
import type { RemoteData } from '../../api/useRemoteData';
import type { PackingResult } from '../../types/packing';

export function useDemoPacking() {
  const health = useRemoteData('health', packingApi.health);
  const scenarios = useRemoteData('scenarios', packingApi.scenarios);
  const [choice, setChoice] = useState<string | null>(null);
  const selectedId = choice ?? (scenarios.state.status === 'success' ? scenarios.state.data[0]?.id ?? null : null);
  const loadScenario = useCallback(
    (signal: AbortSignal) => packingApi.scenario(selectedId ?? '', signal), [selectedId],
  );
  const request = useRemoteData(selectedId, loadScenario);
  const [result, setResult] = useState<RemoteData<PackingResult>>({ status: 'idle' });
  const packingController = useRef<AbortController | null>(null);

  useEffect(() => () => packingController.current?.abort(), []);

  const selectScenario = (id: string) => {
    if (id === selectedId) return;
    packingController.current?.abort();
    setChoice(id);
    setResult({ status: 'idle' });
  };

  const pack = async () => {
    if (request.state.status !== 'success') return;
    packingController.current?.abort();
    const controller = new AbortController();
    packingController.current = controller;
    setResult({ status: 'loading' });
    try {
      const data = await packingApi.pack(request.state.data, controller.signal);
      if (!controller.signal.aborted) setResult({ status: 'success', data });
    } catch (error: unknown) {
      if (!controller.signal.aborted) setResult({ status: 'error', error: toApiError(error) });
    }
  };

  return { health, scenarios, selectedId, selectScenario, request, result, pack };
}
