import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { demoCatalog, demoFixtures, demoScenarios } from './fixtures';
import { responseGuards } from '../../api/responseValidation';
import { validateBox, validateRequest } from '../../api/validation';

const canonicalDirectory = new URL('../../../../demo/', import.meta.url);
const bundledDirectory = new URL('./fixture-data/', import.meta.url);

describe('canonical demo fixtures', () => {
  // Docker intentionally copies only frontend; the complete repo is required for parity.
  it.skipIf(!existsSync(canonicalDirectory))('bundles every canonical JSON file without alteration', () => {
    const files = readdirSync(canonicalDirectory).filter((name) => name.endsWith('.json')).sort();
    expect(readdirSync(bundledDirectory).filter((name) => name.endsWith('.json')).sort()).toEqual(files);
    for (const file of files) {
      expect(readFileSync(new URL(file, bundledDirectory), 'utf8'), fileURLToPath(new URL(file, bundledDirectory)))
        .toBe(readFileSync(new URL(file, canonicalDirectory), 'utf8'));
    }
  });

  it('keeps the catalog and all request/response DTOs conformant', () => {
    for (const box of demoCatalog) expect(validateBox(box)).toEqual({});
    for (const scenario of demoScenarios) {
      const fixture = demoFixtures[scenario.id];
      expect(validateRequest(fixture.request)).toEqual({});
      expect(responseGuards.result(fixture.response), scenario.id).toBe(true);
      expect(fixture.response.status).toBe(scenario.expected_status);
      expect(fixture.response.issues.some((issue) => issue.code === 'DEMO_STUB')).toBe(true);
    }
  });
});
