import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PackingApp } from './pages/PackingApp';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><PackingApp /></StrictMode>,
);
