import { lazy, Suspense, useEffect, useState } from 'react';
import type { PackedBox, PackingRequest, PackingResult, Product } from '../../types/packing';
import { BoxIcon } from '../../components/BoxIcon';
import { Loading } from '../../components/Feedback';
import {
  alternativeTitle,
  dimensions,
  downloadResult,
  getPlacement,
  instanceLabel,
  instructionAt,
  // number,
  optimizationDisplay,
  orientationGuidance,
  percent,
  placementGuidance,
  planSteps,
  productFor,
  selectPlan,
  statusDisplay,
  weight,
} from './presentation';
import type { PackingPlan } from './presentation';
import { UnpackedItems } from './UnpackedItems';

const PackingViewer = lazy(() => import('../../three/PackingViewer'));

function Metrics({ plan }: { plan: PackingPlan }) {
  const m = plan.metrics;
  return (
    <dl className="metrics-grid">
      <div>
        <dt>Коробок</dt>
        <dd>
          {m.boxes_used}
          <small> шт.</small>
        </dd>
      </div>
      <div>
        <dt>Упаковано</dt>
        <dd>
          {m.packed_items}
          <small> / {m.total_items}</small>
        </dd>
      </div>
      <div className={m.unpacked_items ? 'metric-warning' : ''}>
        <dt>Не упаковано</dt>
        <dd>
          {m.unpacked_items}
          <small> шт.</small>
        </dd>
      </div>
      <div title="Суммарный объём товаров / суммарный объём коробок">
        <dt>Общее заполнение</dt>
        <dd>{percent(m.fill_ratio)}</dd>
      </div>
      <div title="Вес уложенных товаров без тары">
        <dt>Вес товаров</dt>
        <dd>{weight(m.total_weight)}</dd>
      </div>
      <div title="Подготовка, размещение товаров и закрытие всех коробок">
        <dt>Шагов</dt>
        <dd>{planSteps(plan)}</dd>
      </div>
    </dl>
  );
}

// function InstructionDetails({ box, step }: { box: PackedBox; step: number }) {
//   const instruction = instructionAt(box, step);
//   const placement = getPlacement(box, step);
//   return (
//     <details className="technical-details" key={step}>
//       <summary>
//         {placement ? 'Точные координаты и инструкция сервера' : 'Инструкция сервера'}
//       </summary>
//       {placement && (
//         <dl>
//           <div>
//             <dt>От левой стенки (x)</dt>
//             <dd>{number(placement.position.x)} мм</dd>
//           </div>
//           <div>
//             <dt>От передней стенки (y)</dt>
//             <dd>{number(placement.position.y)} мм</dd>
//           </div>
//           <div>
//             <dt>От дна (z)</dt>
//             <dd>{number(placement.position.z)} мм</dd>
//           </div>
//           <div>
//             <dt>Размеры после поворота</dt>
//             <dd>{dimensions(placement.dimensions)}</dd>
//           </div>
//           <div>
//             <dt>Ориентация</dt>
//             <dd>{placement.orientation}</dd>
//           </div>
//         </dl>
//       )}
//       <p>{instruction?.message ?? 'Текст инструкции не получен от сервера.'}</p>
//     </details>
//   );
// }

function BoxWorkspace({
  box,
  products,
  onNextBox,
  hasNextBox,
}: {
  box: PackedBox;
  products: Product[];
  onNextBox: () => void;
  hasNextBox: boolean;
}) {
  const [step, setStep] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [playing, setPlaying] = useState(false);
  const finalStep = box.placements.length + 1;
  const placement = getPlacement(box, step);
  const product = placement && productFor(placement, products);
  const instruction = instructionAt(box, step);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(
      () =>
        setStep((previous) => {
          if (previous >= finalStep - 1) {
            setPlaying(false);
            return finalStep;
          }
          return previous + 1;
        }),
      2800,
    );
    const pause = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener('visibilitychange', pause);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', pause);
    };
  }, [playing, finalStep]);

  const go = (next: number) => {
    setPlaying(false);
    setShowAll(false);
    setStep(Math.min(finalStep, Math.max(0, next)));
  };
  const stepLabel =
    step === 0
      ? 'Подготовка коробки'
      : step === finalStep
        ? 'Проверка и закрытие'
        : `Шаг ${step} из ${box.placements.length}`;
  return (
    <div className="packing-workspace" id="packing-workspace" tabIndex={-1}>
      <section className="scene-panel" aria-label="Схема укладки">
        <div className="scene-heading">
          <div>
            <span className="eyebrow">СХЕМА УКЛАДКИ</span>
            <h2>{box.name}</h2>
          </div>
          <div className="scene-heading-actions">
            <span className="dimension-label">
              {showAll
                ? 'Все товары'
                : `Размещено ${Math.min(step, box.placements.length)} из ${box.placements.length}`}
            </span>
            <button
              type="button"
              className="secondary-button"
              aria-pressed={showAll}
              onClick={() => {
                setPlaying(false);
                setShowAll(!showAll);
              }}
            >
              {showAll ? 'Вернуться к шагу' : 'Показать всё'}
            </button>
          </div>
        </div>

        <Suspense fallback={<Loading label="Загружаем 3D-сцену…" />}>
          <PackingViewer box={box} step={step} showAll={showAll} products={products} />
        </Suspense>
      </section>
      <section className="instruction-panel" aria-label="Пошаговая инструкция">
        <div className="instruction-top">
          <span className="eyebrow">ПОРЯДОК УПАКОВКИ</span>
          <span className="step-counter">
            {step} / {finalStep}
          </span>
        </div>
        <div className="progress-track" aria-hidden="true">
          <span style={{ width: `${(step / finalStep) * 100}%` }} />
        </div>
        <div className="current-instruction" aria-live="polite" aria-atomic="true">
          <span className="step-kicker">{stepLabel}</span>
          <h2>
            {step === 0
              ? `Возьмите "${box.name.toLocaleLowerCase('ru-RU')}"`
              : step === finalStep
                ? 'Проверьте содержимое'
                : `Возьмите «${product?.name ?? placement?.product_id ?? 'товар'}»`}
          </h2>
          {placement && (
            <span className="instance-label">
              {instanceLabel(placement, products)} · 1 шт.
              {product ? ` · ${weight(product.weight)}` : ''}
            </span>
          )}
          {step === 0 && (
            <>
              <div className="prepare-box">
                <BoxIcon />
                <div>
                  <strong>{dimensions(box)}</strong>
                  <span>Внутренние размеры · до {weight(box.max_weight)}</span>
                </div>
              </div>
              <p className="instruction-text">
                Поставьте открытую коробку перед собой. На схеме передняя стенка обращена к вам,
                длина считается слева направо.
              </p>
              <p className="instruction-hint">
                Первый товар появится после нажатия «Следующий шаг».
              </p>
            </>
          )}
          {placement && (
            <>
              <div className="instruction-block">
                <span className="mini-step">1</span>
                <div>
                  <h3>Ориентация товара</h3>
                  <p>{orientationGuidance(placement)}</p>
                  {product && !product.allow_rotation && (
                    <span className="rotation-note">Поворот запрещён · исходное положение</span>
                  )}
                </div>
              </div>
              <div className="instruction-block">
                <span className="mini-step">2</span>
                <div>
                  <h3>Положите в коробку</h3>
                  <p>{placementGuidance(placement, box, products)}</p>
                </div>
              </div>
              <p className="instruction-hint">
                Текущий товар выделен контуром и подписью шага на схеме.
              </p>
            </>
          )}
          {step === finalStep && (
            <>
              <div className="close-check">✓</div>
              <p className="instruction-text">
                В коробке должно быть {box.placements.length} шт. товара. Вес —{' '}
                {weight(box.total_weight)} при лимите {weight(box.max_weight)}. Проверьте укладку и
                закройте коробку.
              </p>
              <p className="instruction-hint">
                {hasNextBox
                  ? 'Затем перейдите к следующей коробке.'
                  : 'Это последняя коробка выбранного плана.'}
              </p>
            </>
          )}
          {!instruction && (
            <p className="inline-warning">
              Сервер не передал этот шаг. Сверьте размещение и точные координаты.
            </p>
          )}
        </div>
        {/*<InstructionDetails box={box} step={step} />*/}
        <div className="step-controls">
          <button
            className="secondary-button"
            type="button"
            onClick={() => go(step - 1)}
            disabled={step === 0}
          >
            ← Назад
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={() => (step === finalStep && hasNextBox ? onNextBox() : go(step + 1))}
            disabled={step === finalStep && !hasNextBox}
          >
            {step === finalStep
              ? hasNextBox
                ? 'Следующая коробка →'
                : 'Все шаги пройдены'
              : 'Следующий шаг →'}
          </button>
        </div>
        <button
          type="button"
          className="play-button"
          onClick={() => {
            if (step === finalStep) setStep(0);
            setShowAll(false);
            setPlaying(!playing);
          }}
        >
          {playing ? 'Ⅱ Приостановить показ' : '▷ Автопоказ шагов'}
        </button>
        {/*<details className="step-list">
          <summary>Все шаги этой коробки</summary>
          <ol>
            {box.instructions.map((item) => (
              <li key={item.step}>
                <button
                  type="button"
                  aria-current={step === item.step ? 'step' : undefined}
                  onClick={() => go(item.step)}
                >
                  <span>{item.step < step ? '✓' : item.step}</span>
                  {item.action === 'prepare_box'
                    ? 'Подготовка коробки'
                    : item.action === 'close_box'
                      ? 'Проверка и закрытие'
                      : (products.find((p) => p.id === item.product_id)?.name ?? item.product_id)}
                </button>
              </li>
            ))}
          </ol>
        </details>*/}
      </section>
    </div>
  );
}

export function PackingResultView({
  result,
  request,
  orderId,
  stale,
  onEdit,
}: {
  result: PackingResult;
  request: PackingRequest;
  orderId: string;
  stale: boolean;
  onEdit: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [boxIndex, setBoxIndex] = useState(0);
  const plan = selectPlan(result, selectedId);
  const pageSize = 12;
  const pageStart = Math.floor(boxIndex / pageSize) * pageSize;
  const box = plan.packed_boxes[boxIndex];
  const status = statusDisplay(plan.status, plan.issues);
  const optimization = optimizationDisplay(result, request, selectedId !== null);
  const demo =
    result.issues.some((issue) => issue.code === 'DEMO_STUB') ||
    result.algorithm_version.startsWith('demo-stub');
  return (
    <>
      <div className="result-screen screen-only">
        <div className="page-heading">
          <div>
            {/*<span className="eyebrow">ЗАКАЗ {orderId}</span>*/}
            <h1>Заказ {orderId}</h1>
            {result.calculation_seconds != null && <p>Время построения плана: {result.calculation_seconds.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} с</p>}
            {/*<p>Одна коробка за другой. Каждый товар на своём месте.</p>*/}
          </div>
          <div className="heading-actions">
            {box && (
              <a className="primary-button start-packing" href="#packing-workspace">
                К инструкции ↓
              </a>
            )}
            <button
              type="button"
              className="secondary-button"
              onClick={() => downloadResult(orderId, request, result, selectedId)}
            >
              ↓ Экспорт JSON
            </button>
          </div>
        </div>
        
        <UnpackedItems key={selectedId ?? 'recommended'} plan={plan} />

        {stale && (
          <div className="notice notice-warning" role="status">
            <strong>Данные заказа изменились.</strong>
            <span>
              Этот план относится к предыдущему составу. Пересчитайте упаковку перед работой.
            </span>
            <button className="text-button" type="button" onClick={onEdit}>
              К заказу →
            </button>
          </div>
        )}
        {demo && (
          <div className="notice notice-demo">
            <span className="demo-tag">ДЕМО-ПЛАН</span>
            <span>
              Готовый пример укладки. Для изменённого заказа потребуется расчёт на сервере.
            </span>
          </div>
        )}
        <section className="result-summary">
          <div className="summary-status" role="status">
            <span className={`status-badge status-${status.tone}`}>
              <span aria-hidden="true">{status.symbol}</span>
              {status.label}
            </span>
            <span className="muted">
              {plan.metrics.packed_items} из {plan.metrics.total_items} товаров размещено
            </span>
          </div>
          <Metrics plan={plan} />
        </section>
        <section className={`optimization-summary optimization-${optimization.tone}`} aria-label="Алгоритм и качество решения">
          <div>
            {/*<span className="eyebrow">ВЫБРАНО: {optimization.requested}</span>*/}
            <strong>Рассчитано: {optimization.actual}</strong>
          </div>
          <div>
            <strong>{optimization.title}</strong>
            <p>{optimization.detail}</p>
          </div>
        </section>
        {result.alternatives.length > 0 && (
          <details className="alternatives">
            <summary>
              Сравнить варианты упаковки <span>+{Math.min(3, result.alternatives.length)}</span>
            </summary>
            <div className="alternative-grid">
              <button
                className={`alternative-card ${selectedId === null ? 'selected' : ''}`}
                type="button"
                aria-pressed={selectedId === null}
                onClick={() => {
                  setSelectedId(null);
                  setBoxIndex(0);
                }}
              >
                <strong>Рекомендуемый</strong>
                <span>
                  {result.metrics.boxes_used} коробок · {percent(result.metrics.fill_ratio)}
                </span>
                <small>
                  {result.metrics.packed_items} из {result.metrics.total_items} товаров
                </small>
              </button>
              {[...result.alternatives].sort((a, b) => b.metrics.fill_ratio - a.metrics.fill_ratio).slice(0, 3).map((alternative, index) => (
                <button
                  className={`alternative-card ${selectedId === alternative.id ? 'selected' : ''}`}
                  type="button"
                  key={alternative.id}
                  aria-pressed={selectedId === alternative.id}
                  onClick={() => {
                    setSelectedId(alternative.id);
                    setBoxIndex(0);
                  }}
                >
                  <strong>{alternativeTitle(alternative, index)}</strong>
                  <span>
                    {alternative.metrics.boxes_used} коробок ·{' '}
                    {percent(alternative.metrics.fill_ratio)}
                  </span>
                  <small>
                    {statusDisplay(alternative.status, alternative.issues).label} ·{' '}
                    {alternative.metrics.packed_items} товаров
                  </small>
                </button>
              ))}
            </div>
          </details>
        )}
        {box ? (
          <>
            <div className="box-section-heading">
              <h2>Выберите коробку</h2>
              <span className="muted">
                Коробка {boxIndex + 1} / {plan.packed_boxes.length}
              </span>
            </div>
            {plan.packed_boxes.length > pageSize && (
              <div className="box-pagination">
                <button type="button" className="secondary-button" disabled={pageStart === 0} onClick={() => setBoxIndex(pageStart - pageSize)}>← Предыдущие коробки</button>
                <label>Номер коробки
                  <select aria-label="Номер коробки" value={boxIndex} onChange={(event) => setBoxIndex(Number(event.target.value))}>
                    {plan.packed_boxes.map((item, index) => <option key={item.id} value={index}>{index + 1} / {plan.packed_boxes.length} · {item.name}</option>)}
                  </select>
                </label>
                <button type="button" className="secondary-button" disabled={pageStart + pageSize >= plan.packed_boxes.length} onClick={() => setBoxIndex(pageStart + pageSize)}>Следующие коробки →</button>
              </div>
            )}
            <div className="box-selector" aria-label="Коробки плана">
              {plan.packed_boxes.slice(pageStart, pageStart + pageSize).map((item, offset) => {
                const index = pageStart + offset;
                return (
                <button
                  type="button"
                  key={item.id}
                  className={`box-card ${index === boxIndex ? 'selected' : ''}`}
                  aria-pressed={index === boxIndex}
                  onClick={() => setBoxIndex(index)}
                >
                  <span className="box-card-icon">
                    <BoxIcon />
                    <b>{String(index + 1).padStart(2, '0')}</b>
                  </span>
                  <span className="box-card-content">
                    <strong>
                      {item.name}
                      <span>{index === boxIndex ? 'Выбрана' : `№ ${index + 1}`}</span>
                    </strong>
                    <span>{dimensions(item)}</span>
                    <span className="fill-track" aria-hidden="true">
                      <i style={{ width: `${item.fill_ratio * 100}%` }} />
                    </span>
                    <span>
                      {percent(item.fill_ratio)} заполнено · {weight(item.total_weight)} /{' '}
                      {weight(item.max_weight)}
                    </span>
                    <span>
                      {item.placements.length} товаров · слоёв:{' '}
                      {new Set(item.placements.map((p) => p.position.z)).size}
                    </span>
                  </span>
                </button>
                );
              })}
            </div>
            <BoxWorkspace
              key={`${selectedId ?? 'main'}:${box.id}`}
              box={box}
              products={request.products}
              hasNextBox={boxIndex < plan.packed_boxes.length - 1}
              onNextBox={() => setBoxIndex(boxIndex + 1)}
            />
          </>
        ) : (
          <div className="empty-result">
            <BoxIcon />
            <h2>Для этого заказа нет плана укладки</h2>
            <p>Проверьте причины ниже, измените товары или доступные коробки и повторите расчёт.</p>
            <button type="button" className="primary-button" onClick={onEdit}>
              Изменить заказ →
            </button>
          </div>
        )}
        
        {/*<div className="result-footnote">
          Вес указан без тары. Расчёт не списывает остатки коробок.
        </div>*/}
      </div>
    </>
  );
}
