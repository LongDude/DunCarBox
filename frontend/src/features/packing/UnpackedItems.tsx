import { useId, useMemo, useState } from 'react';
import { dimensions, issueLabels, weight } from './presentation';
import type { PackingPlan } from './presentation';
import { groupUnpackedItems } from './unpackedGroups';

const previewCount = 5;

export function UnpackedItems({ plan }: { plan: PackingPlan }) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const groups = useMemo(
    () => groupUnpackedItems(plan.unpacked_items, plan.issues),
    [plan.unpacked_items, plan.issues],
  );
  if (groups.length === 0) return null;
  const visibleGroups = expanded ? groups : groups.slice(0, previewCount);

  return (
    <section className="unpacked-panel" aria-labelledby={`${listId}-title`}>
      <div className="section-heading">
        <h2 id={`${listId}-title`}>Осталось без упаковки</h2>
        <span className="count-badge">{plan.metrics.unpacked_items.toLocaleString('ru-RU')} шт.</span>
      </div>
      <div className="unpacked-list-controls">
        <span>Одинаковые товары сгруппированы по причинам · {groups.length} поз.</span>
        {groups.length > previewCount && (
          <button
            type="button"
            className="text-button"
            aria-expanded={expanded}
            aria-controls={listId}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Свернуть список' : `Показать все ${groups.length} позиций`}
          </button>
        )}
      </div>
      <div
        id={listId}
        className="unpacked-list-scroll"
        tabIndex={0}
        role="region"
        aria-label="Неупакованные товары и причины"
      >
        <ul className="unpacked-list">
          {visibleGroups.map(({ key, item, quantity, reasons }) => (
            <li key={key}>
              <div>
                <strong>{item.name} · {quantity.toLocaleString('ru-RU')} шт.</strong>
                <span>{dimensions(item)} · {weight(item.weight)} / шт.</span>
              </div>
              <span>{reasons.map((reason) => issueLabels[reason]).join(' · ') || 'Размещение не найдено'}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
