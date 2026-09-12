import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { CalculationProgress } from './CalculationProgress';

it('shows an indeterminate progress bar while preparing', () => {
  const html = renderToStaticMarkup(<CalculationProgress progress={null} elapsedSeconds={62} />);
  expect(html).toContain('<progress');
  expect(html).not.toContain('value=');
  expect(html).toContain('1 мин 2 с');
});

it('labels solver progress as consumed time rather than solution completeness', () => {
  const html = renderToStaticMarkup(<CalculationProgress
    progress={{ stage: 'solver', progress: 0.5, elapsed_seconds: 10 }} elapsedSeconds={9}
  />);
  expect(html).toContain('value="0.5"');
  expect(html).toContain('50% бюджета времени');
  expect(html).toContain('0 мин 10 с');
});
