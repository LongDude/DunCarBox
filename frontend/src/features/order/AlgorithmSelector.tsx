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
            ? 'До 16 предметов и 64 доступных мест под коробки. Полная опора под каждым товаром. При превышении лимитов или отсутствии результата — эвристика с явной отметкой и той же опорой 100%.'
            : 'Быстро сравнивает несколько вариантов укладки. Не гарантирует математический оптимум. Опора — не менее 80% основания.'}
      </p>
      {!demo && settings.algorithm === 'z3' && (
        <div className="solver-settings">
          <label>
            Лимит поиска, с
            <input
              type="number"
              min={1}
              max={60}
              step={0.001}
              value={Number.isFinite(settings.solver_timeout_ms) ? settings.solver_timeout_ms / 1_000 : ''}
              aria-invalid={Boolean(errors['options.solver_timeout_ms'])}
              aria-describedby={errors['options.solver_timeout_ms'] ? 'solver-timeout-error' : undefined}
              onChange={(event) => onChange({ ...settings, solver_timeout_ms: event.target.value === '' ? NaN : Math.round(Number(event.target.value) * 1_000 * 1e6) / 1e6 })}
            />
          </label>
          {errors['options.solver_timeout_ms'] && <p id="solver-timeout-error" className="field-error">Укажите от 1 до 60 секунд с точностью до миллисекунды.</p>}
          <label>
            Параллельные процессы
            <input
              type="number"
              min={1}
              max={8}
              step={1}
              value={Number.isFinite(settings.solver_workers) ? settings.solver_workers : ''}
              aria-invalid={Boolean(errors['options.solver_workers'])}
              aria-describedby={errors['options.solver_workers'] ? 'solver-workers-error' : 'solver-workers-hint'}
              onChange={(event) => onChange({ ...settings, solver_workers: event.target.value === '' ? NaN : Number(event.target.value) })}
            />
          </label>
          {errors['options.solver_workers'] && <p id="solver-workers-error" className="field-error">Укажите целое число от 1 до 8.</p>}
          <p id="solver-workers-hint" className="summary-note">По умолчанию 4. На сервере с 10 и более ядрами можно выбрать 8. Лимит времени относится к поиску, подготовка и проверка плана добавляют время.</p>
        </div>
      )}
    </fieldset>
  );
}
