import { afterEach, expect, it, vi } from 'vitest';
import { ALGORITHM_STORAGE_KEY, defaultAlgorithmSettings, readAlgorithmSettings, saveAlgorithmSettings } from './algorithmSettings';

afterEach(() => vi.unstubAllGlobals());

it('restores valid API settings but rejects malformed or obsolete saved options', () => {
  let value = JSON.stringify({ algorithm: 'z3', solver_timeout_ms: 25_000, solver_workers: 8 });
  vi.stubGlobal('localStorage', { getItem: () => value });
  expect(readAlgorithmSettings()).toEqual({ algorithm: 'z3', solver_timeout_ms: 25_000, solver_workers: 8 });
  for (const damaged of ['{', 'null', '{"algorithm":"z3"}', '{"algorithm":"z3","solver_timeout_ms":10000,"solver_workers":20}']) {
    value = damaged;
    expect(readAlgorithmSettings()).toEqual(defaultAlgorithmSettings);
  }
});

it('persists only valid choices and tolerates unavailable browser storage', () => {
  const setItem = vi.fn();
  vi.stubGlobal('localStorage', { setItem });
  saveAlgorithmSettings({ ...defaultAlgorithmSettings, algorithm: 'z3' });
  expect(setItem).toHaveBeenCalledWith(ALGORITHM_STORAGE_KEY, JSON.stringify({ ...defaultAlgorithmSettings, algorithm: 'z3' }));
  saveAlgorithmSettings({ ...defaultAlgorithmSettings, solver_workers: NaN });
  expect(setItem).toHaveBeenCalledTimes(1);
  vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } });
  expect(readAlgorithmSettings()).toEqual(defaultAlgorithmSettings);
  expect(() => saveAlgorithmSettings(defaultAlgorithmSettings)).not.toThrow();
});
