import catalog from './fixture-data/catalog.boxes.json';
import scenarios from './fixture-data/scenarios.json';
import simpleRequest from './fixture-data/simple-order.request.json';
import simpleResponse from './fixture-data/simple-order.response.json';
import multipleRequest from './fixture-data/multiple-boxes.request.json';
import multipleResponse from './fixture-data/multiple-boxes.response.json';
import oversizedRequest from './fixture-data/oversized.request.json';
import oversizedResponse from './fixture-data/oversized.response.json';
import shortageRequest from './fixture-data/stock-shortage.request.json';
import shortageResponse from './fixture-data/stock-shortage.response.json';
import type { BoxType, DemoScenario, PackingRequest, PackingResult } from '../../types/packing';

/** Canonical demo/*.json copies also work in the isolated frontend Docker build.
 * After changing canonical fixtures run (from repo root):
 * Copy-Item demo/*.json frontend/src/features/demo/fixture-data/
 * fixtures.test.ts checks that the bundled data remains identical to demo/.
 */
export const demoCatalog = catalog as BoxType[];
export const demoScenarios = scenarios as DemoScenario[];
export const demoFixtures: Record<string, { request: PackingRequest; response: PackingResult }> = {
  'simple-order': { request: simpleRequest as PackingRequest, response: simpleResponse as PackingResult },
  'multiple-boxes': { request: multipleRequest as PackingRequest, response: multipleResponse as PackingResult },
  oversized: { request: oversizedRequest as PackingRequest, response: oversizedResponse as PackingResult },
  'stock-shortage': { request: shortageRequest as PackingRequest, response: shortageResponse as PackingResult },
};
