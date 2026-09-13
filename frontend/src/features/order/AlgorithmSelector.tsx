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
            ? 'Ищет максимальное заполнение. Если бюджет поиска исчерпан, возвращает лучший найденный план.'
            : 'Сравнивает варианты укладки, не гарантирует математический оптимум.'}
      </p>
      {!demo && (
        <div className="solver-settings">
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
              ? 'Независимые стратегии работают параллельно.'
              : 'Каждый процесс ищет свой вариант решения.'}
          </p>
        </div>
      )}
    </fieldset>
  );
}
