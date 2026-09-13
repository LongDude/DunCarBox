import type { ItemInstance, IssueCode, PackingIssue } from '../../types/packing';

export interface UnpackedGroup {
  key: string;
  item: ItemInstance;
  quantity: number;
  reasons: IssueCode[];
}

export function groupUnpackedItems(items: ItemInstance[], issues: PackingIssue[]): UnpackedGroup[] {
  const reasonsByItem = new Map<string, Set<IssueCode>>();
  for (const issue of issues) {
    for (const id of issue.item_instance_ids) {
      const reasons = reasonsByItem.get(id) ?? new Set<IssueCode>();
      reasons.add(issue.code);
      reasonsByItem.set(id, reasons);
    }
  }

  const groups = new Map<string, UnpackedGroup>();
  for (const item of items) {
    const reasons = [...(reasonsByItem.get(item.id) ?? [])].sort();
    const key = JSON.stringify([
      item.product_id, item.name, item.length, item.width, item.height,
      item.weight, item.allow_rotation, reasons,
    ]);
    const group = groups.get(key);
    if (group) group.quantity += 1;
    else groups.set(key, { key, item, quantity: 1, reasons });
  }
  return [...groups.values()];
}
