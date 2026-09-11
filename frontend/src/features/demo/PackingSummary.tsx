import type { PackingResult, PackingStatus } from '../../types/packing';

export const statusLabels: Record<PackingStatus, string> = {
  success: 'Всё упаковано',
  partial: 'Упакована часть заказа',
  impossible: 'Не удалось упаковать',
};

export function PackingSummary({ result }: { result: PackingResult }) {
  const metrics = result.metrics;
  return (
    <div className="packing-summary">
      <div className="result-heading">
        <span className={`status-badge status-${result.status}`}>{statusLabels[result.status]}</span>
        <span className="muted">Демо-результат</span>
      </div>
      <dl className="metrics-grid">
        <div><dt>Коробок</dt><dd>{metrics.boxes_used}</dd></div>
        <div><dt>Упаковано</dt><dd>{metrics.packed_items}<small> / {metrics.total_items}</small></dd></div>
        <div><dt>Заполнение</dt><dd>{(metrics.fill_ratio * 100).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}<small>%</small></dd></div>
        <div><dt>Вес товаров</dt><dd>{(metrics.total_weight / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 3 })}<small> кг</small></dd></div>
      </dl>
      {result.issues.length > 0 && (
        <ul className="issues-list" aria-label="Пояснения к результату">
          {result.issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className={`issue issue-${issue.severity}`}>
              <span className="issue-dot" aria-hidden="true" />{issue.message}
            </li>
          ))}
        </ul>
      )}
      {result.unpacked_items.length > 0 && (
        <div className="unpacked-items">
          <h3>Осталось без упаковки · {metrics.unpacked_items} шт.</h3>
          <ul>{result.unpacked_items.map((item) => <li key={item.id}>{item.name} · экземпляр {item.unit_index}</li>)}</ul>
        </div>
      )}
      {result.packed_boxes.length > 0 && (
        <div className="instructions">
          <h3>Инструкция по упаковке</h3>
          <p className="muted">Последовательность действий для каждой коробки.</p>
          {result.packed_boxes.map((box) => (
            <details className="instruction-box" key={box.id} open>
              <summary>{box.name} <span>· {box.placements.length} шт.</span></summary>
              <ol className="steps">
                {box.instructions.map((instruction) => (
                  <li key={instruction.step}>
                    <span className="step-number" aria-hidden="true">{instruction.step + 1}</span>
                    <p>{instruction.message}</p>
                  </li>
                ))}
              </ol>
            </details>
          ))}
        </div>
      )}
      {result.alternatives.length > 0 && (
        <p className="alternative-note">В ответе также есть альтернативные планы: {result.alternatives.length}. Их сравнение появится на следующем этапе.</p>
      )}
    </div>
  );
}
