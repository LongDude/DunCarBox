import type { ApiError } from '../api/client';

export function ErrorNotice({ error, retry }: { error: ApiError; retry: () => void }) {
  return (
    <div className="error-notice" role="alert">
      <p>{error.message}</p>
      {error.details.length > 0 && (
        <ul>{error.details.map((detail, index) => (
          <li key={`${detail.field}-${index}`}>{detail.field}: {detail.message}</li>
        ))}</ul>
      )}
      <button className="text-button" type="button" onClick={retry}>Повторить попытку ↻</button>
    </div>
  );
}

export function Loading({ label = 'Загрузка…' }: { label?: string }) {
  return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{label}</div>;
}
