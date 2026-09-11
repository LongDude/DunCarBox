import type { ApiError } from '../api/client';
import { apiErrorDetailMessage, fieldLabel } from '../api/validation';

export function ErrorNotice({
  error,
  retry,
  retryLabel = 'Повторить попытку ↻',
}: {
  error: ApiError;
  retry: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="error-notice" role="alert">
      <p>{error.message}</p>
      {error.details.length > 0 && (
        <ul>
          {error.details.map((detail, index) => (
            <li key={`${detail.field}-${index}`}>
              {fieldLabel(detail.field)}: {apiErrorDetailMessage(detail)}
            </li>
          ))}
        </ul>
      )}
      <button className="text-button" type="button" onClick={retry}>
        {retryLabel}
      </button>
    </div>
  );
}

export function Loading({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}
