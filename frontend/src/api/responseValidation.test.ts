import { expect, it } from 'vitest';
import { demoFixtures } from '../features/demo/fixtures';
import { responseGuards } from './responseValidation';

const result = demoFixtures['simple-order'].response;
const optimization = { status: 'fallback', reason: 'size_limit', workers: 0, time_limit_ms: 1000, support_ratio: 1 };

it('keeps old fixtures compatible and accepts valid optimization metadata including a solver skipped by size limit', () => {
  expect(responseGuards.result(result)).toBe(true);
  expect(responseGuards.result({ ...result, optimization: null })).toBe(true);
  expect(responseGuards.result({ ...result, optimization })).toBe(true);
  expect(responseGuards.result({ ...result, optimization: { ...optimization, reason: 'resource_limit', time_limit_ms: null } })).toBe(true);
  expect(responseGuards.result({ ...result, optimization: { ...optimization, status: 'optimal', reason: 'completed', time_limit_ms: null } })).toBe(true);
});

it.each([
  { status: 'unknown' }, { reason: 'unknown' }, { workers: -1 }, { workers: 1.5 },
  { time_limit_ms: 0 }, { time_limit_ms: '1000' }, { support_ratio: 1.1 },
])('rejects malformed optimization metadata %j before rendering', (change) => {
  expect(responseGuards.result({ ...result, optimization: { ...optimization, ...change } })).toBe(false);
});
