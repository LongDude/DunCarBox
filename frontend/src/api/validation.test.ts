import { describe, expect, it } from 'vitest';
import { demoFixtures } from '../features/demo/fixtures';
import { ApiError } from './client';
import { apiErrorDetailMessage, apiErrorFields, fieldLabel, validateBox, validateRequest } from './validation';

const request = () => structuredClone(demoFixtures['simple-order'].request);

describe('contract input validation', () => {
  it('validates optimizer options, integer boundaries and readable backend errors', () => {
    expect(validateRequest({ ...request(), options: { algorithm: 'z3', solver_timeout_ms: 1000, solver_workers: 8 } })).toEqual({});
    expect(validateRequest({ ...request(), options: { algorithm: 'z3', solver_timeout_ms: 600000, solver_workers: 32 } })).toEqual({});
    for (const [field, values] of Object.entries({ algorithm: ['other', null], solver_timeout_ms: [0, -1, 1000.1, true, '1000'], solver_workers: [0, -1, 1.5, true, '4'] })) {
      for (const value of values) expect(validateRequest({ ...request(), options: { [field]: value } })[`options.${field}`]).toBeTruthy();
    }
    expect(fieldLabel('body.options.solver_workers')).toBe('Параллельные процессы Z3');
    expect(apiErrorDetailMessage({ field: 'body.options.solver_timeout_ms', message: 'Input should be greater than 0', type: 'greater_than' })).toContain('положительное время');
  });
  it('allows empty box snapshots and preserves zero stock as valid domain constraints', () => {
    const input = request();
    input.boxes[0].available_count = 0;
    expect(validateRequest(input)).toEqual({});
    input.boxes = [];
    expect(validateRequest(input)).toEqual({});
  });

  it.each([0, -1, 100001, 1.5, NaN, Infinity, true, '100'])('rejects invalid dimension %s with a field path', (value) => {
    const input = request();
    const product = { ...input.products[0], length: value };
    expect(validateRequest({ ...input, products: [product] })['products.0.length']).toBeTruthy();
  });

  it('validates quantity totals, duplicate IDs and array limits', () => {
    const input = request();
    input.products[0].quantity = 600;
    input.products.push({ ...input.products[0] });
    const errors = validateRequest(input);
    expect(errors.products).toBeUndefined();
    expect(errors['products.0.id']).toBeTruthy();
    expect(errors['products.1.id']).toBeTruthy();
    expect(validateRequest({ ...request(), boxes: Array.from({ length: 101 }, (_, index) => ({ ...request().boxes[0], id: `b${index}` })) })).toEqual({});
    expect(validateRequest({ ...request(), products: Array.from({ length: 201 }, (_, index) => ({ ...request().products[0], id: `p${index}`, quantity: 10000 })) })).toEqual({});
    expect(validateRequest({ ...request(), products: [] }).products).toBeTruthy();
  });

  it('validates weight, name, identifier, stock and optional defaults', () => {
    const box = request().boxes[0];
    expect(validateBox({ ...box, name: '  ' }).name).toBeTruthy();
    expect(validateBox({ ...box, id: 'bad id' }).id).toBeTruthy();
    expect(validateBox({ ...box, max_weight: 100000001 }).max_weight).toBeTruthy();
    expect(validateBox({ ...box, available_count: 10000000000 })).toEqual({});
    expect(validateRequest({ ...request(), options: {} })).toEqual({});
    expect(validateRequest({ ...request(), options: { max_alternatives: 6 } })['options.max_alternatives']).toBeTruthy();
    expect(validateRequest({ ...request(), options: { include_alternatives: 'true' } })['options.include_alternatives']).toBeTruthy();
    expect(validateRequest({ ...request(), surprise: true }).surprise).toBeTruthy();
  });

  it('converts API field paths and validation details into Russian form messages', () => {
    const detail = { field: 'body.products.0.length', message: 'Input should be greater than 0', type: 'greater_than' };
    expect(fieldLabel(detail.field)).toBe('Товар 1 · Длина, мм');
    expect(apiErrorDetailMessage(detail)).toBe('Значение должно быть больше нуля.');
    expect(apiErrorFields(new ApiError('Validation', 'VALIDATION_ERROR', 422, [detail])))
      .toEqual({ 'products.0.length': 'Значение должно быть больше нуля.' });
  });
});
