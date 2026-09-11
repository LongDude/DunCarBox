import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { createDataSource } from '../api/dataSource';
import type { DataSourceMode } from '../api/dataSource';
import { toApiError } from '../api/client';
import type { ApiError } from '../api/client';
import { apiErrorFields, fieldLabel, validateRequest } from '../api/validation';
import { useRemoteData } from '../api/useRemoteData';
import { BoxIcon } from '../components/BoxIcon';
import { ErrorNotice, Loading } from '../components/Feedback';
import { BoxCatalog } from '../features/catalog/BoxCatalog';
import { createProduct, ProductEditor } from '../features/order/ProductEditor';
import { PackingResultView } from '../features/packing/PackingResultView';
import { dimensions, weight } from '../features/packing/presentation';
import type { BoxType, PackingRequest, PackingResult, Product } from '../types/packing';

type View = 'order' | 'result' | 'catalog';
interface CalculatedOrder {
  result: PackingResult;
  request: PackingRequest;
  orderId: string;
}

function initialMode(): DataSourceMode {
  const param = new URLSearchParams(window.location.search).get('mode');
  return param === 'demo' || (param !== 'api' && import.meta.env.VITE_DATA_SOURCE === 'demo')
    ? 'demo'
    : 'api';
}

function Workspace({
  mode,
  onModeChange,
}: {
  mode: DataSourceMode;
  onModeChange: (mode: DataSourceMode) => void;
}) {
  const source = useMemo(() => createDataSource(mode), [mode]);
  const health = useRemoteData('health', source.health);
  const catalog = useRemoteData('catalog', source.boxes.list);
  const scenarios = useRemoteData('scenarios', source.scenarios);
  const [view, setView] = useState<View>('order');
  const [products, setProducts] = useState<Product[]>(() => [createProduct()]);
  const [scenarioBoxes, setScenarioBoxes] = useState<BoxType[] | null>(null);
  const [scenarioName, setScenarioName] = useState('');
  const [selectedScenario, setSelectedScenario] = useState('multiple-boxes');
  const [orderId, setOrderId] = useState('ЗК-001');
  const [includeAlternatives, setIncludeAlternatives] = useState(true);
  const [calculated, setCalculated] = useState<CalculatedOrder | null>(null);
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [errorOrigin, setErrorOrigin] = useState<'demo' | 'pack'>('pack');
  const [resultVersion, setResultVersion] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const packingController = useRef<AbortController | null>(null);
  const demoController = useRef<AbortController | null>(null);
  const orderForm = useRef<HTMLFormElement>(null);
  const headingFocus = useRef<HTMLDivElement>(null);
  const boxes = scenarioBoxes ?? (catalog.state.status === 'success' ? catalog.state.data : []);
  const request: PackingRequest = {
    boxes,
    products,
    options: { include_alternatives: includeAlternatives, max_alternatives: 3 },
  };
  const normalizedRequest = {
    ...request,
    products: products.map((product) => ({ ...product, name: product.name.trim() })),
  };
  const stale = Boolean(
    calculated &&
    (JSON.stringify(normalizedRequest) !== JSON.stringify(calculated.request) ||
      orderId.trim() !== calculated.orderId),
  );

  useEffect(
    () => () => {
      packingController.current?.abort();
      demoController.current?.abort();
    },
    [],
  );
  useEffect(() => {
    headingFocus.current?.focus({ preventScroll: true });
  }, [view]);

  const invalidate = () => {
    packingController.current?.abort();
    packingController.current = null;
    setLoading(false);
    setError(null);
    setErrors({});
  };
  const changeProducts = (next: Product[]) => {
    invalidate();
    setProducts(next);
  };

  const loadDemo = async () => {
    invalidate();
    demoController.current?.abort();
    const controller = new AbortController();
    demoController.current = controller;
    setDemoLoading(true);
    setErrorOrigin('demo');
    try {
      const snapshot = await source.scenario(selectedScenario, controller.signal);
      if (controller.signal.aborted) return;
      setProducts(snapshot.products);
      setScenarioBoxes(snapshot.boxes);
      setIncludeAlternatives(snapshot.options?.include_alternatives ?? true);
      setScenarioName(
        scenarios.state.status === 'success'
          ? (scenarios.state.data.find((scenario) => scenario.id === selectedScenario)?.name ??
              'Демо-заказ')
          : 'Демо-заказ',
      );
      setOrderId(`ДЕМО-${selectedScenario}`);
      setView('order');
    } catch (failure) {
      if (!controller.signal.aborted) setError(toApiError(failure));
    } finally {
      if (!controller.signal.aborted) {
        setDemoLoading(false);
        demoController.current = null;
      }
    }
  };

  const calculate = async (event?: FormEvent) => {
    event?.preventDefault();
    if (packingController.current || demoLoading) return;
    const validation = validateRequest(request);
    if (!orderId.trim()) validation.order_id = 'Укажите номер заказа.';
    setErrors(validation);
    setError(null);
    setErrorOrigin('pack');
    if (Object.keys(validation).length) {
      window.requestAnimationFrame(() =>
        orderForm.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(),
      );
      return;
    }
    const controller = new AbortController();
    packingController.current = controller;
    const snapshot = structuredClone(request);
    snapshot.products.forEach((product) => {
      product.name = product.name.trim();
    });
    setLoading(true);
    setView('result');
    try {
      const result = await source.pack(snapshot, controller.signal);
      if (!controller.signal.aborted) {
        setCalculated({ result, request: snapshot, orderId: orderId.trim() });
        setResultVersion((value) => value + 1);
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        const problem = toApiError(failure);
        setError(problem);
        setErrors(apiErrorFields(problem));
        setView('order');
      }
    } finally {
      if (!controller.signal.aborted) {
        packingController.current = null;
        setLoading(false);
      }
    }
  };

  const newOrder = () => {
    invalidate();
    demoController.current?.abort();
    setDemoLoading(false);
    setProducts([createProduct()]);
    setScenarioBoxes(null);
    setScenarioName('');
    setOrderId('ЗК-001');
    setCalculated(null);
    setView('order');
  };
  const updateCatalog = async (action: () => Promise<unknown>) => {
    await action();
    catalog.retry();
  };
  const totalItems = products.reduce(
    (sum, product) => sum + (Number.isFinite(product.quantity) ? product.quantity : 0),
    0,
  );
  const totalWeight = products.reduce(
    (sum, product) =>
      sum +
      (Number.isFinite(product.quantity * product.weight) ? product.quantity * product.weight : 0),
    0,
  );
  const serverStub =
    mode === 'api' &&
    health.state.status === 'success' &&
    health.state.data.engine.startsWith('demo-stub');

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Перейти к содержимому
      </a>
      <header className="app-header screen-only">
        <a
          href="#main"
          className="brand"
          onClick={() => setView('order')}
          aria-label="DunCarBox — к заказу"
        >
          <span className="brand-icon">
            <BoxIcon />
          </span>
          <span>
            DunCarBox<small>РАБОЧЕЕ МЕСТО УПАКОВЩИКА</small>
          </span>
        </a>
        <div className="header-right">
          <div className="connection" role="status">
            <span
              className={`connection-dot ${health.state.status === 'success' ? 'online' : health.state.status === 'error' ? 'offline' : ''}`}
            />
            {mode === 'demo'
              ? 'Локальная демонстрация'
              : health.state.status === 'success'
                ? 'Сервис подключён'
                : health.state.status === 'error'
                  ? 'Нет подключения'
                  : 'Подключение…'}
            {mode === 'api' && health.state.status === 'error' && (
              <button type="button" className="text-button" onClick={health.retry}>
                Повторить
              </button>
            )}
          </div>
          <label className="source-selector">
            <span className="sr-only">Источник данных</span>
            <select
              value={mode}
              onChange={(event) => onModeChange(event.target.value as DataSourceMode)}
            >
              <option value="api">Сервер</option>
              <option value="demo">Демо без сервера</option>
            </select>
          </label>
        </div>
      </header>
      <div className="navigation-bar screen-only">
        <nav aria-label="Основные разделы">
          <button
            type="button"
            className={view === 'order' ? 'active' : ''}
            aria-current={view === 'order' ? 'page' : undefined}
            onClick={() => setView('order')}
          >
            <span>01</span> Заказ
          </button>
          <button
            type="button"
            className={view === 'result' ? 'active' : ''}
            aria-current={view === 'result' ? 'page' : undefined}
            disabled={!calculated && !loading}
            onClick={() => setView('result')}
          >
            <span>02</span> План упаковки
            {stale && <i className="stale-dot" title="Данные изменились" />}
          </button>
          <button
            type="button"
            className={view === 'catalog' ? 'active' : ''}
            aria-current={view === 'catalog' ? 'page' : undefined}
            onClick={() => setView('catalog')}
          >
            Каталог коробок
          </button>
        </nav>
        <span className="workspace-label">DUN / PACK STATION</span>
      </div>
      <main id="main">
        <div
          ref={headingFocus}
          tabIndex={-1}
          className="view-focus"
          aria-label={
            view === 'order'
              ? 'Состав заказа'
              : view === 'result'
                ? 'План упаковки'
                : 'Каталог коробок'
          }
        />
        {mode === 'demo' && view !== 'result' && (
          <div className="notice notice-demo screen-only">
            <span className="demo-tag">ДЕМО БЕЗ СЕРВЕРА</span>
            <span>Четыре готовых сценария. Каталог сохраняется только в этом браузере.</span>
          </div>
        )}
        {mode === 'api' && health.state.status === 'error' && (
          <div className="notice notice-warning screen-only">
            <div>
              <strong>Сервис сейчас недоступен.</strong>
              <span> Можно проверить все шаги упаковки на готовых примерах.</span>
            </div>
            <button type="button" className="secondary-button" onClick={() => onModeChange('demo')}>
              Открыть демо без сервера →
            </button>
          </div>
        )}
        {serverStub && (
          <div className="notice notice-demo screen-only">
            <span className="demo-tag">ДЕМО-СЕРВЕР</span>
            <span>
              Сервис воспроизводит готовые сценарии. Расчёт изменённых заказов пока недоступен.
            </span>
          </div>
        )}
        {view === 'order' && (
          <div className="order-screen screen-only">
            <div className="page-heading">
              <div>
                <span className="eyebrow">ПОДГОТОВКА К УПАКОВКЕ</span>
                <h1>
                  Соберите заказ.
                  <br className="mobile-only" /> Мы подберём коробки.
                </h1>
                <p>Укажите товары и доступные коробки — получите наглядный план укладки.</p>
              </div>
              <button type="button" className="secondary-button" onClick={newOrder}>
                + Новый заказ
              </button>
            </div>
            <section className="demo-loader" aria-label="Загрузка демонстрационного заказа">
              <div className="demo-loader-intro">
                <span className="demo-spark" aria-hidden="true">
                  ↗
                </span>
                <div>
                  <strong>Попробуйте на готовом заказе</strong>
                  <p>От простой укладки до нехватки коробок.</p>
                </div>
              </div>
              <div className="demo-loader-controls">
                <label>
                  <span className="sr-only">Демо-сценарий</span>
                  <select
                    value={selectedScenario}
                    onChange={(event) => setSelectedScenario(event.target.value)}
                    disabled={demoLoading || scenarios.state.status !== 'success'}
                  >
                    {scenarios.state.status === 'success' ? (
                      scenarios.state.data.map((scenario) => (
                        <option value={scenario.id} key={scenario.id}>
                          {scenario.name}
                        </option>
                      ))
                    ) : (
                      <option value="multiple-boxes">Загрузка сценариев…</option>
                    )}
                  </select>
                </label>
                <button
                  type="button"
                  className="demo-button"
                  onClick={() => void loadDemo()}
                  disabled={
                    demoLoading ||
                    loading ||
                    scenarios.state.status !== 'success' ||
                    scenarios.state.data.length === 0
                  }
                >
                  {demoLoading ? 'Загружаем…' : 'Загрузить демо-заказ'}
                  <span aria-hidden="true">↓</span>
                </button>
              </div>
            </section>
            {scenarios.state.status === 'error' && (
              <ErrorNotice error={scenarios.state.error} retry={scenarios.retry} />
            )}
            <form noValidate ref={orderForm} onSubmit={(event) => void calculate(event)}>
              <div className="order-layout">
                <section className="panel order-panel">
                  <div className="section-heading">
                    <div className="section-title">
                      <span className="panel-number">01</span>
                      <h2>Товары в заказе</h2>
                    </div>
                    <label className="order-id-label">
                      Номер заказа
                      <input
                        value={orderId}
                        maxLength={80}
                        aria-invalid={Boolean(errors.order_id)}
                        aria-describedby={errors.order_id ? 'order-id-error' : undefined}
                        onChange={(event) => {
                          invalidate();
                          setOrderId(event.target.value);
                        }}
                        disabled={demoLoading || loading}
                      />
                    </label>
                  </div>
                  {errors.order_id && (
                    <p id="order-id-error" className="field-error">
                      {errors.order_id}
                    </p>
                  )}
                  <p className="panel-description">
                    Размеры упаковки товара в миллиметрах. Вес одной единицы в граммах.
                  </p>
                  <ProductEditor
                    products={products}
                    onChange={changeProducts}
                    disabled={demoLoading || loading}
                    errors={errors}
                  />
                </section>
                <aside className="panel order-summary">
                  <span className="eyebrow">К РАСЧЁТУ</span>
                  <h2>Ваш заказ</h2>
                  <dl>
                    <div>
                      <dt>Видов товаров</dt>
                      <dd>{products.length}</dd>
                    </div>
                    <div>
                      <dt>Всего единиц</dt>
                      <dd>{totalItems} шт.</dd>
                    </div>
                    <div>
                      <dt>Общий вес</dt>
                      <dd>{weight(totalWeight)}</dd>
                    </div>
                    <div>
                      <dt>Доступно коробок</dt>
                      <dd>{boxes.reduce((sum, box) => sum + box.available_count, 0)} шт.</dd>
                    </div>
                  </dl>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={includeAlternatives}
                      disabled={loading || demoLoading}
                      onChange={(event) => {
                        invalidate();
                        setIncludeAlternatives(event.target.checked);
                      }}
                    />
                    Предложить альтернативы
                  </label>
                  <button
                    className="primary-button calculate-button"
                    type="submit"
                    disabled={
                      loading ||
                      demoLoading ||
                      (scenarioBoxes === null && catalog.state.status !== 'success')
                    }
                  >
                    {loading ? 'Рассчитываем…' : 'Рассчитать упаковку'}
                    <span aria-hidden="true">→</span>
                  </button>
                  <p className="summary-note">
                    Вы получите выбор коробок, 3D-схему и инструкцию для каждого товара.
                  </p>
                </aside>
              </div>
              {Object.keys(errors).length > 0 && (
                <div className="error-notice" role="alert">
                  <strong>Проверьте данные заказа</strong>
                  <ul>
                    {Object.entries(errors).map(([field, message]) => (
                      <li key={field}>
                        {field === 'order_id' ? 'Номер заказа' : fieldLabel(field)}: {message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </form>
            {error && (
              <ErrorNotice
                error={error}
                retry={() =>
                  errorOrigin === 'demo' || error.code === 'ENGINE_NOT_IMPLEMENTED'
                    ? void loadDemo()
                    : void calculate()
                }
                retryLabel={
                  error.code === 'ENGINE_NOT_IMPLEMENTED'
                    ? 'Загрузить демо-заказ заново'
                    : undefined
                }
              />
            )}
            <section className="panel available-boxes">
              <div className="section-heading">
                <div className="section-title">
                  <span className="panel-number">02</span>
                  <h2>Доступные коробки</h2>
                </div>
                <button type="button" className="text-button" onClick={() => setView('catalog')}>
                  Открыть каталог →
                </button>
              </div>
              <p className="panel-description">
                {scenarioBoxes
                  ? `Коробки сценария «${scenarioName}». Остатки каталога не изменены.`
                  : 'В расчёт войдут текущие остатки каталога. Упаковка не списывает коробки.'}
              </p>
              {scenarioBoxes && (
                <button
                  type="button"
                  className="secondary-button use-catalog"
                  disabled={loading || demoLoading || catalog.state.status !== 'success'}
                  onClick={() => {
                    invalidate();
                    setScenarioBoxes(null);
                    setScenarioName('');
                  }}
                >
                  Использовать коробки из каталога
                </button>
              )}
              {scenarioBoxes === null && catalog.state.status === 'loading' && (
                <Loading label="Загружаем каталог…" />
              )}
              {scenarioBoxes === null && catalog.state.status === 'error' && (
                <ErrorNotice error={catalog.state.error} retry={catalog.retry} />
              )}
              {boxes.length > 0 ? (
                <div className="stock-grid">
                  {boxes.map((box) => (
                    <article className="stock-card" key={box.id}>
                      <BoxIcon />
                      <div>
                        <strong>{box.name}</strong>
                        <p>
                          {dimensions(box)} · до {weight(box.max_weight)}
                        </p>
                        <span className={box.available_count === 0 ? 'stock-empty' : 'stock-count'}>
                          {box.available_count === 0
                            ? 'Нет в наличии'
                            : `${box.available_count} шт. в наличии`}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                catalog.state.status === 'success' && (
                  <p className="empty-catalog-note">
                    В каталоге пока нет коробок. Добавьте тип коробки или загрузите демо-заказ.
                  </p>
                )
              )}
            </section>
          </div>
        )}
        {view === 'catalog' && (
          <div className="screen-only">
            <div className="page-heading">
              <div>
                <span className="eyebrow">УПРАВЛЕНИЕ ЗАПАСАМИ</span>
                <h1>Каталог коробок</h1>
                <p>Внутренние размеры, допустимый вес и остатки на рабочем месте.</p>
              </div>
            </div>
            <BoxCatalog
              boxes={catalog.state.status === 'success' ? catalog.state.data : []}
              loading={catalog.state.status === 'loading'}
              error={catalog.state.status === 'error' ? catalog.state.error : null}
              onReload={catalog.retry}
              onCreate={(box) => updateCatalog(() => source.boxes.create(box))}
              onUpdate={(box) => updateCatalog(() => source.boxes.update(box))}
              onDelete={(id) => updateCatalog(() => source.boxes.remove(id))}
            />
          </div>
        )}
        {view === 'result' &&
          (loading ? (
            <section className="result-loading screen-only" aria-busy="true">
              <Loading label="Подбираем коробки и готовим пошаговый план…" />
              <div className="skeleton-metrics" />
              <div className="skeleton-scene" />
              <button
                className="secondary-button"
                type="button"
                onClick={() => {
                  invalidate();
                  setView('order');
                }}
              >
                Отменить расчёт
              </button>
            </section>
          ) : calculated ? (
            <PackingResultView
              key={resultVersion}
              {...calculated}
              stale={stale}
              onEdit={() => setView('order')}
            />
          ) : null)}
      </main>
      <footer className="app-footer screen-only">
        <span>
          DunCarBox<span className="footer-divider">/</span>Каждому товару — своё место
        </span>
        <span>Размеры в мм · Вес без тары</span>
      </footer>
    </div>
  );
}

export function PackingApp() {
  const [mode, setMode] = useState<DataSourceMode>(initialMode);
  return <Workspace key={mode} mode={mode} onModeChange={setMode} />;
}
