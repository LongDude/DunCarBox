import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { CalculationProgress } from './CalculationProgress';

it('shows an indeterminate progress bar while preparing', () => {
  const html = renderToStaticMarkup(<CalculationProgress progress={null} elapsedSeconds={62} />);
  expect(html).toContain('<progress');
  expect(html).not.toContain('value=');
  expect(html).toContain('1 мин 2 с');
});

it('shows unbounded solver search without a time budget or a misleading percentage', () => {
  const html = renderToStaticMarkup(<CalculationProgress
    progress={{ stage: 'solver', progress: 0.5, elapsed_seconds: 10 }} elapsedSeconds={9}
  />);
  expect(html).not.toContain('value=');
  expect(html).not.toContain('50%');
  expect(html).toContain('без ограничения времени');
  expect(html).toContain('можно отменить');
  expect(html).toContain('0 мин 10 с');
});

it('retains measured progress for heuristic stages', () => {
  const html = renderToStaticMarkup(<CalculationProgress
    progress={{ stage: 'heuristic', progress: 0.5, elapsed_seconds: 10 }} elapsedSeconds={9}
  />);
  expect(html).toContain('value="0.5"');
  expect(html).toContain('50% этапа');
});
