export function BoxIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path d="m24 5 18 9v21l-18 9-18-9V14L24 5Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="m6 14 18 9 18-9M24 23v21M15 9.5l18 9V27" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}
