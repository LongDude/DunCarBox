import { BoxIcon } from '../components/BoxIcon';
import { ErrorNotice, Loading } from '../components/Feedback';
import { useDemoPacking } from '../features/demo/useDemoPacking';
import { PackingSummary, statusLabels } from '../features/demo/PackingSummary';
import { RequestSnapshot } from '../features/demo/RequestSnapshot';

export function FoundationPage() {
  const demo = useDemoPacking();
  const health = demo.health.state;
  const scenarios = demo.scenarios.state;
  const request = demo.request.state;
  const result = demo.result;

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">Перейти к содержимому</a>
      <header className="app-header">
        <a className="brand" href="/" aria-label="DunCarBox — главная"><BoxIcon /><span>DunCarBox</span></a>
        <div className="connection" role="status">
          <span className={`connection-dot ${health.status === 'success' ? 'online' : health.status === 'error' ? 'offline' : ''}`} />
          {health.status === 'success' ? 'Сервис подключён' : health.status === 'error' ? 'Нет подключения' : 'Подключение…'}
          {health.status === 'error' && <button className="text-button" onClick={demo.health.retry} type="button">Повторить</button>}
        </div>
      </header>
      <main id="main">
        <section className="intro" aria-labelledby="page-title">
          <span className="eyebrow">УПАКОВКА ЗАКАЗОВ</span>
          <h1 id="page-title">Каждому товару —<br />своё место.</h1>
          <p>Коробки, размещение и понятные шаги упаковки<br className="desktop-break" /> в одном плане.</p>
        </section>
        <div className="demo-notice">
          <span className="demo-tag">Демонстрационный режим</span>
          <p>Четыре готовых сценария с заранее подготовленными результатами. Расчёт произвольных заказов появится после подключения алгоритма.</p>
        </div>
        <div className="workspace-grid">
          <section className="panel scenario-panel" aria-labelledby="scenario-title">
            <div className="panel-heading"><span className="panel-number">01</span><h2 id="scenario-title">Выберите сценарий</h2></div>
            <p className="panel-description">Посмотрите, как выглядит план в разных ситуациях.</p>
            {scenarios.status === 'loading' && <Loading label="Загружаем сценарии…" />}
            {scenarios.status === 'error' && <ErrorNotice error={scenarios.error} retry={demo.scenarios.retry} />}
            {scenarios.status === 'success' && (
              <div className="scenario-grid" aria-label="Демонстрационные сценарии">
                {scenarios.data.map((scenario, index) => (
                  <button
                    className={`scenario-card ${demo.selectedId === scenario.id ? 'selected' : ''}`}
                    key={scenario.id}
                    type="button"
                    aria-pressed={demo.selectedId === scenario.id}
                    onClick={() => demo.selectScenario(scenario.id)}
                  >
                    <span className="scenario-index">0{index + 1}<span aria-hidden="true">{demo.selectedId === scenario.id ? '●' : '○'}</span></span>
                    <strong>{scenario.name}</strong>
                    <span className="scenario-description">{scenario.description}</span>
                    <span className="scenario-outcome">{statusLabels[scenario.expected_status]}</span>
                  </button>
                ))}
              </div>
            )}
            {scenarios.status === 'success' && scenarios.data.length === 0 && <p className="muted">Пока нет доступных сценариев.</p>}
            {request.status === 'loading' && <Loading label="Загружаем состав заказа…" />}
            {request.status === 'error' && <ErrorNotice error={request.error} retry={demo.request.retry} />}
            {request.status === 'success' && <RequestSnapshot request={request.data} />}
            <button
              className="primary-button"
              type="button"
              disabled={request.status !== 'success' || result.status === 'loading'}
              onClick={() => void demo.pack()}
            >
              {result.status === 'loading' ? 'Получаем план…' : 'Показать демо-план'}
              <span aria-hidden="true">→</span>
            </button>
          </section>
          <section className="panel result-panel" aria-labelledby="result-title" aria-busy={result.status === 'loading'}>
            <div className="panel-heading"><span className="panel-number">02</span><h2 id="result-title">План упаковки</h2></div>
            <div aria-live="polite" aria-atomic="true" className="sr-only">
              {result.status === 'success' ? statusLabels[result.data.status] : ''}
            </div>
            {result.status === 'idle' && (
              <div className="empty-result"><div className="empty-icon"><BoxIcon /></div><h3>Здесь появится ваш план</h3><p>Выберите сценарий и нажмите<br />«Показать демо-план».</p><span className="empty-caption">Коробки · Метрики · Инструкция</span></div>
            )}
            {result.status === 'loading' && <Loading label="Получаем план упаковки…" />}
            {result.status === 'error' && <ErrorNotice error={result.error} retry={() => void demo.pack()} />}
            {result.status === 'success' && <PackingSummary result={result.data} />}
          </section>
        </div>
      </main>
      <footer className="app-footer"><span>DunCarBox · Основа сервиса</span><span>Размеры в мм · Вес в г</span></footer>
    </div>
  );
}
