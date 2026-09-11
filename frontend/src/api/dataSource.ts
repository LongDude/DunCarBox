import { demoCatalog, demoFixtures, demoScenarios } from '../features/demo/fixtures';
import type {
  BoxType,
  DemoScenario,
  HealthResponse,
  PackingRequest,
  PackingResult,
} from '../types/packing';
import { ApiError } from './client';
import { boxesApi, packingApi } from './packing';
import { assertValid, inputLimits, validateBox, validateRequest } from './validation';

export type DataSourceMode = 'api' | 'demo';
export interface DataSource {
  health(signal?: AbortSignal): Promise<HealthResponse>;
  scenarios(signal?: AbortSignal): Promise<DemoScenario[]>;
  scenario(id: string, signal?: AbortSignal): Promise<PackingRequest>;
  pack(request: PackingRequest, signal?: AbortSignal): Promise<PackingResult>;
  boxes: {
    list(signal?: AbortSignal): Promise<BoxType[]>;
    create(box: BoxType): Promise<BoxType>;
    update(box: BoxType): Promise<BoxType>;
    remove(id: string): Promise<void>;
  };
}

export const DEMO_CATALOG_STORAGE_KEY = 'duncarbox.demo.catalog.v1';
let memoryCatalog = structuredClone(demoCatalog);

function copy<T>(value: T): T {
  return structuredClone(value);
}

function readCatalog(): BoxType[] {
  try {
    const saved = globalThis.localStorage?.getItem(DEMO_CATALOG_STORAGE_KEY);
    if (saved !== null && saved !== undefined) {
      const parsed: unknown = JSON.parse(saved);
      if (
        Array.isArray(parsed) &&
        parsed.length <= inputLimits.boxTypes &&
        parsed.every((box: unknown) => Object.keys(validateBox(box)).length === 0) &&
        new Set(parsed.map((box: BoxType) => box.id)).size === parsed.length
      ) {
        memoryCatalog = parsed as BoxType[];
      }
    }
  } catch {
    /* Private mode, disabled storage or damaged demo data: keep this session usable. */
  }
  return copy(memoryCatalog).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

function saveCatalog(boxes: BoxType[]) {
  memoryCatalog = copy(boxes);
  try {
    globalThis.localStorage?.setItem(DEMO_CATALOG_STORAGE_KEY, JSON.stringify(boxes));
  } catch {
    /* In-memory demo editing remains available if browser persistence is disabled. */
  }
}

function abortError() {
  return new DOMException('Действие отменено.', 'AbortError');
}

/** Short cancellable boundary keeps local and remote consumers on the same async interface. */
async function localResponse<T>(produce: () => T, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) throw abortError();
  await new Promise<void>((resolve, reject) => {
    const finish = () => {
      signal?.removeEventListener('abort', abort);
      resolve();
    };
    const timer = globalThis.setTimeout(finish, 120);
    const abort = () => {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      reject(abortError());
    };
    signal?.addEventListener('abort', abort, { once: true });
  });
  if (signal?.aborted) throw abortError();
  return copy(produce());
}

/** Explicit keys make request matching independent of row AND JSON property ordering. */
function requestSignature(request: PackingRequest): string {
  const boxes = request.boxes
    .map((box) => ({
      id: box.id,
      name: box.name.trim(),
      length: box.length,
      width: box.width,
      height: box.height,
      max_weight: box.max_weight,
      available_count: box.available_count,
    }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const products = request.products
    .map((product) => ({
      id: product.id,
      name: product.name.trim(),
      length: product.length,
      width: product.width,
      height: product.height,
      weight: product.weight,
      quantity: product.quantity,
      allow_rotation: product.allow_rotation ?? true,
    }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return JSON.stringify({ boxes, products });
}

const fixtureBySignature = new Map(
  Object.values(demoFixtures).map((fixture) => [
    requestSignature(fixture.request),
    fixture.response,
  ]),
);

function packDemo(request: PackingRequest): PackingResult {
  assertValid(validateRequest(request));
  const fixture = fixtureBySignature.get(requestSignature(request));
  if (!fixture) {
    throw new ApiError(
      'Демонстрационный режим воспроизводит только готовые сценарии. Загрузите демо-заказ заново или подключите API с движком для расчёта изменённого заказа.',
      'ENGINE_NOT_IMPLEMENTED',
      503,
    );
  }
  const result = copy(fixture);
  const limit =
    request.options?.include_alternatives === false ? 0 : (request.options?.max_alternatives ?? 3);
  result.alternatives = result.alternatives.slice(0, limit);
  return result;
}

const demoSource: DataSource = {
  health: (signal) =>
    localResponse(() => ({ status: 'ok', api_version: 'v1', engine: 'demo-stub-v1' }), signal),
  scenarios: (signal) => localResponse(() => demoScenarios, signal),
  scenario: (id, signal) =>
    localResponse(() => {
      const fixture = Object.hasOwn(demoFixtures, id) ? demoFixtures[id] : undefined;
      if (!fixture) throw new ApiError('Демонстрационный сценарий не найден.', 'NOT_FOUND', 404);
      return fixture.request;
    }, signal),
  pack: (request, signal) => {
    const snapshot = copy(request);
    return localResponse(() => packDemo(snapshot), signal);
  },
  boxes: {
    list: (signal) => localResponse(readCatalog, signal),
    create: (box) => {
      const snapshot = copy(box);
      return localResponse(() => {
        assertValid(validateBox(snapshot));
        const catalog = readCatalog();
        if (catalog.some((entry) => entry.id === snapshot.id))
          throw new ApiError(
            'Коробка с таким идентификатором уже есть. Укажите другой идентификатор.',
            'CONFLICT',
            409,
          );
        if (catalog.length >= inputLimits.boxTypes)
          assertValid({ boxes: 'В каталоге допускается не более 100 типов коробок.' });
        const normalized = { ...snapshot, name: snapshot.name.trim() };
        saveCatalog([...catalog, normalized]);
        return normalized;
      });
    },
    update: (box) => {
      const snapshot = copy(box);
      return localResponse(() => {
        assertValid(validateBox(snapshot));
        const catalog = readCatalog();
        if (!catalog.some((entry) => entry.id === snapshot.id))
          throw new ApiError('Коробка уже удалена. Обновите каталог.', 'NOT_FOUND', 404);
        const normalized = { ...snapshot, name: snapshot.name.trim() };
        saveCatalog(catalog.map((entry) => (entry.id === snapshot.id ? normalized : entry)));
        return normalized;
      });
    },
    remove: (id) =>
      localResponse(() => {
        const catalog = readCatalog();
        if (!catalog.some((box) => box.id === id))
          throw new ApiError('Коробка уже удалена. Обновите каталог.', 'NOT_FOUND', 404);
        saveCatalog(catalog.filter((box) => box.id !== id));
      }),
  },
};

/** UI components depend only on this adapter; switching never silently changes sources. */
export function createDataSource(mode: DataSourceMode): DataSource {
  return mode === 'demo' ? demoSource : { ...packingApi, boxes: boxesApi };
}
