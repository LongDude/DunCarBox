import type { PackingAlgorithm } from '../../types/packing';
import { isRecord } from '../../api/validation';

export interface AlgorithmSettings {
  algorithm: PackingAlgorithm;
  solver_workers: number;
}

export const ALGORITHM_STORAGE_KEY = 'duncarbox.algorithm.v1';
export const defaultAlgorithmSettings: AlgorithmSettings = {
  algorithm: 'heuristic',
  solver_workers: 4,
};

function validSettings(value: unknown): value is AlgorithmSettings {
  return isRecord(value) &&
    (value.algorithm === 'heuristic' || value.algorithm === 'z3') &&
    typeof value.solver_workers === 'number' && Number.isSafeInteger(value.solver_workers) &&
    value.solver_workers >= 1;
}

export function readAlgorithmSettings(): AlgorithmSettings {
  try {
    const saved: unknown = JSON.parse(globalThis.localStorage?.getItem(ALGORITHM_STORAGE_KEY) ?? 'null');
    if (validSettings(saved)) return { algorithm: saved.algorithm, solver_workers: saved.solver_workers };
  } catch {
    // The form stays usable when browser storage is unavailable or damaged.
  }
  return { ...defaultAlgorithmSettings };
}

export function saveAlgorithmSettings(settings: AlgorithmSettings): void {
  if (!validSettings(settings)) return;
  try {
    globalThis.localStorage?.setItem(ALGORITHM_STORAGE_KEY, JSON.stringify({
      algorithm: settings.algorithm,
      solver_workers: settings.solver_workers,
    }));
  } catch {
    // Valid settings remain active for this workspace even without persistence.
  }
}
