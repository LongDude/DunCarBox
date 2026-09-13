import { describe, expect, it } from 'vitest';
import type { ItemInstance, PackingIssue } from '../../types/packing';
import { groupUnpackedItems } from './unpackedGroups';

const item: ItemInstance = {
  id: 'gift:1', product_id: 'gift', name: 'Подарок', unit_index: 1,
  length: 200, width: 100, height: 50, weight: 300, allow_rotation: true,
};
const issue: PackingIssue = {
  code: 'BOX_STOCK_EXHAUSTED', severity: 'warning', message: 'Нет коробок',
  item_instance_ids: ['gift:1', 'gift:2'], box_type_ids: [],
};

describe('groupUnpackedItems', () => {
  it('combines repeated units while preserving their quantity and reasons', () => {
    const groups = groupUnpackedItems([
      item, { ...item, id: 'gift:2', unit_index: 2 },
    ], [issue, issue]);
    expect(groups).toHaveLength(1);
    expect(groups[0].quantity).toBe(2);
    expect(groups[0].reasons).toEqual(['BOX_STOCK_EXHAUSTED']);
  });

  it('keeps units with different reasons separate and preserves items without diagnostics', () => {
    const groups = groupUnpackedItems([
      item, { ...item, id: 'gift:2', unit_index: 2 }, { ...item, id: 'gift:3', unit_index: 3 },
    ], [{ ...issue, item_instance_ids: ['gift:1'] }, {
      ...issue, code: 'ITEM_TOO_HEAVY', item_instance_ids: ['gift:2'],
    }]);
    expect(groups.map(({ quantity, reasons }) => ({ quantity, reasons }))).toEqual([
      { quantity: 1, reasons: ['BOX_STOCK_EXHAUSTED'] },
      { quantity: 1, reasons: ['ITEM_TOO_HEAVY'] },
      { quantity: 1, reasons: [] },
    ]);
  });

  it('does not merge different products sharing a display name', () => {
    const groups = groupUnpackedItems([item, { ...item, id: 'other:1', product_id: 'other' }], []);
    expect(groups).toHaveLength(2);
  });

  it('reduces a large repeated order to one row without losing units', () => {
    const items = Array.from({ length: 10_000 }, (_, index) => ({
      ...item, id: `gift:${index + 1}`, unit_index: index + 1,
    }));
    const groups = groupUnpackedItems(items, [{ ...issue, item_instance_ids: items.map(({ id }) => id) }]);
    expect(groups).toHaveLength(1);
    expect(groups[0].quantity).toBe(10_000);
  });
});
