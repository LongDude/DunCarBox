import type { FieldErrors } from '../../api/validation';
import type { PackingAlgorithm } from '../../types/packing';
import type { AlgorithmSettings } from './algorithmSettings';

export function AlgorithmSelector({
  settings,
  onChange,
  disabled,
  demo,
  errors,
}: {
  settings: AlgorithmSettings;
  onChange: (settings: AlgorithmSettings) => void;
  disabled: boolean;
  demo: boolean;
  errors: FieldErrors;
}) {
  return (
    <fieldset className="algorithm-settings" disabled={disabled}>
      <legend>Алгоритм расчёта</legend>
      <label>
        <span className="sr-only">Алгоритм расчёта</span>
        <select
          value={demo ? 'demo' : settings.algorithm}
          disabled={demo}
          aria-invalid={Boolean(errors['options.algorithm'])}
          aria-describedby="algorithm-description"
          onChange={(event) => onChange({ ...settings, algorithm: event.target.value as PackingAlgorithm })}
        >
          {demo && <option value="demo">Готовый демо-план</option>}
          <option value="heuristic">1 · Быстрая эвристика</option>
          <option value="z3">2 · Оптимизатор Z3</option>
        </select>
      </label>
      <p id="algorithm-description" className="summary-note">
        {demo
          ? 'Демо воспроизводит готовые планы. Для выбора алгоритма и нового расчёта переключитесь на «Сервер».'
          : settings.algorithm === 'z3'
            ? 'Ищет оптимальный план с полной опорой под каждым товаром. Для больших заказов поиск может не завершиться за выбранное время: тогда используется лучший найденный план или резервная эвристика с опорой 100%.'
            : 'Сравнивает варианты укладки, приоритет — упаковать товары и увеличить общее заполнение. Не гарантирует математический оптимум. Опора — не менее 80% основания.'}
      </p>
      {!demo && (
        <div className="solver-settings">
          {settings.algorithm === 'z3' && <>
          <label>
            Лимит поиска, с
            <input
              type="number"
              min={0.001}
              step={0.001}
              value={Number.isFinite(settings.solver_timeout_ms) ? settings.solver_timeout_ms / 1_000 : ''}
              aria-invalid={Boolean(errors['options.solver_timeout_ms'])}
              aria-describedby={errors['options.solver_timeout_ms'] ? 'solver-timeout-error' : undefined}
              onChange={(event) => onChange({ ...settings, solver_timeout_ms: event.target.value === '' ? NaN : Math.round(Number(event.target.value) * 1_000 * 1e6) / 1e6 })}
            />
          </label>
          {errors['options.solver_timeout_ms'] && <p id="solver-timeout-error" className="field-error">Укажите положительное время с точностью до миллисекунды.</p>}
          <p className="summary-note">Лимит включает предварительную укладку, подготовку модели и поиск Z3. Проверка, остановка процессов и передача результата могут добавить время.</p>
          </>}
          <label>
            Параллельные процессы
            <input
              type="number"
              min={1}
              step={1}
              value={Number.isFinite(settings.solver_workers) ? settings.solver_workers : ''}
              aria-invalid={Boolean(errors['options.solver_workers'])}
              aria-describedby={errors['options.solver_workers'] ? 'solver-workers-error' : 'solver-workers-hint'}
              onChange={(event) => onChange({ ...settings, solver_workers: event.target.value === '' ? NaN : Number(event.target.value) })}
            />
          </label>
          {errors['options.solver_workers'] && <p id="solver-workers-error" className="field-error">Укажите положительное целое число.</p>}
          <p id="solver-workers-hint" className="summary-note">
            {settings.algorithm === 'heuristic'
              ? 'Независимые стратегии работают параллельно: до 12 процессов и не больше доступных ядер. Для заказов меньше 100 единиц используется один процесс, чтобы не тратить время на запуск.'
              : 'По умолчанию 4. Можно указать 24; сервер использует не больше доступных ядер. Каждый процесс ищет свой вариант решения.'}
          </p>
        </div>
      )}
    </fieldset>
  );
}
