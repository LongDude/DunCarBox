import type { PackingProgress } from '../../api/packingJobs';

const stageLabels: Record<string, string> = {
  preparing: 'Подготавливаем заказ',
  heuristic: 'Сравниваем варианты укладки',
  solver: 'Ищем лучший план Z3',
  repacking: 'Упорядочиваем товары в коробках',
  instructions: 'Строим пошаговые инструкции',
  validating: 'Проверяем и сохраняем план',
  completed: 'План готов',
};

export function CalculationProgress({ progress, elapsedSeconds }: {
  progress: PackingProgress | null;
  elapsedSeconds: number;
}) {
  const stage = progress?.stage ?? 'preparing';
  const fraction = stage === 'solver' ? null : progress?.progress;
  const seconds = Math.floor(Math.max(elapsedSeconds, progress?.elapsed_seconds ?? 0));
  return (
    <div className="calculation-progress">
      <p role="status">{stageLabels[stage] ?? 'Рассчитываем упаковку'}…</p>
      <progress
        max={1}
        value={fraction ?? undefined}
        aria-label={stage === 'solver' ? 'Поиск оптимального плана Z3' : 'Прогресс текущего этапа'}
      />
      <p className="muted">
        {fraction != null && `${Math.floor(fraction * 100)}% этапа · `}
        Прошло: {Math.floor(seconds / 60)} мин {seconds % 60} с
      </p>
      {stage === 'solver' && <p className="summary-note">Поиск идёт без ограничения времени. Расчёт можно отменить.</p>}
    </div>
  );
}
