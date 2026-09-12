import { useEffect, useRef, useState } from 'react';
import { inputLimits, validateRequest } from '../../api/validation';
import type { Product } from '../../types/packing';
import './forms.css';

type NumericField = 'length' | 'width' | 'height' | 'weight' | 'quantity';

const numericFields: { key: NumericField; label: string; unit: string; max: number }[] = [
  { key: 'length', label: 'Длина', unit: 'мм', max: inputLimits.dimension },
  { key: 'width', label: 'Ширина', unit: 'мм', max: inputLimits.dimension },
  { key: 'height', label: 'Высота', unit: 'мм', max: inputLimits.dimension },
  { key: 'weight', label: 'Вес', unit: 'г', max: inputLimits.weight },
  { key: 'quantity', label: 'Кол-во', unit: 'шт.', max: inputLimits.productQuantity },
];

let nextProductId = 1;

export function createProduct(existing: Product[] = []): Product {
  const ids = new Set(existing.map((product) => product.id));
  while (ids.has(`product-${nextProductId}`)) nextProductId += 1;
  const id = `product-${nextProductId++}`;
  return {
    id,
    name: '',
    length: Number.NaN,
    width: Number.NaN,
    height: Number.NaN,
    weight: Number.NaN,
    quantity: 1,
    allow_rotation: true,
  };
}

export function validateProducts(products: Product[]): Record<string, string> {
  return validateRequest({ boxes: [], products });
}

interface ProductEditorProps {
  products: Product[];
  onChange: (products: Product[]) => void;
  disabled?: boolean;
  errors?: Record<string, string>;
}

function RowActionIcon({ kind }: { kind: 'duplicate' | 'remove' }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      {kind === 'duplicate' ? (
        <>
          <rect x="7" y="7" width="10" height="10" rx="2" />
          <path d="M13 4V3H3v10h1" />
        </>
      ) : (
        <>
          <path d="M3 5h14M8 2h4M6 5l1 12h6l1-12M9 8v6M11 8v6" />
        </>
      )}
    </svg>
  );
}

export function ProductEditor({
  products,
  onChange,
  disabled = false,
  errors = {},
}: ProductEditorProps) {
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [focusId, setFocusId] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const validation = validateProducts(products);
  const total = products.reduce(
    (sum, product) => sum + (Number.isFinite(product.quantity) ? product.quantity : 0),
    0,
  );

  useEffect(() => {
    if (!focusId) return;
    editorRef.current?.querySelector<HTMLInputElement>(`[data-product-id="${focusId}"]`)?.focus();
    setFocusId(null);
  }, [focusId, products]);

  const update = (id: string, patch: Partial<Product>) => {
    onChange(products.map((product) => (product.id === id ? { ...product, ...patch } : product)));
  };

  const add = (source?: Product) => {
    const product = createProduct(products);
    const next = source
      ? { ...source, id: product.id, name: `${source.name.slice(0, 192)} (копия)` }
      : product;
    onChange([...products, next]);
    setFocusId(next.id);
  };

  const fieldError = (product: Product, index: number, field: string) => {
    const path = `products.${index}.${field}`;
    return (
      errors[path] ??
      errors[`body.${path}`] ??
      (touched[`${product.id}.${field}`] ? validation[path] : undefined)
    );
  };

  return (
    <div className="product-editor" ref={editorRef} aria-busy={disabled}>
      {products.length > 0 ? (
        <div
          className="product-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Таблица товаров, доступна горизонтальная прокрутка"
        >
          <table className="product-table">
            <caption className="sr-only">Ввод товаров для расчёта упаковки</caption>
            <thead>
              <tr>
                <th scope="col" className="product-index">
                  №
                </th>
                <th scope="col">Название товара</th>
                {numericFields.map(({ key, label, unit }) => (
                  <th scope="col" key={key}>
                    {label}
                    <span>{unit}</span>
                  </th>
                ))}
                <th scope="col" className="product-rotation">
                  Поворот<span>разрешён</span>
                </th>
                <th scope="col">
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {products.map((product, index) => {
                const nameError = fieldError(product, index, 'name');
                return (
                  <tr key={product.id}>
                    <td className="product-index">{String(index + 1).padStart(2, '0')}</td>
                    <td className="product-name-cell">
                      <input
                        type="text"
                        name={`products.${index}.name`}
                        data-product-id={product.id}
                        value={product.name}
                        required
                        maxLength={200}
                        disabled={disabled}
                        placeholder="Например, наушники"
                        aria-label={`Название товара ${index + 1}`}
                        aria-invalid={!!nameError}
                        aria-describedby={nameError ? `${product.id}-name-error` : undefined}
                        onChange={(event) => update(product.id, { name: event.target.value })}
                        onBlur={() =>
                          setTouched((current) => ({ ...current, [`${product.id}.name`]: true }))
                        }
                      />
                      {nameError && (
                        <span className="form-field-error" id={`${product.id}-name-error`}>
                          {nameError}
                        </span>
                      )}
                    </td>
                    {numericFields.map(({ key, label, unit, max }) => {
                      const error = fieldError(product, index, key);
                      return (
                        <td key={key}>
                          <input
                            type="number"
                            name={`products.${index}.${key}`}
                            required
                            min={1}
                            max={max}
                            step={1}
                            inputMode="numeric"
                            value={Number.isFinite(product[key]) ? product[key] : ''}
                            disabled={disabled}
                            placeholder="—"
                            aria-label={`${label} товара ${index + 1}, ${unit}`}
                            aria-invalid={!!error}
                            aria-describedby={error ? `${product.id}-${key}-error` : undefined}
                            onChange={(event) =>
                              update(product.id, { [key]: event.target.valueAsNumber })
                            }
                            onBlur={() =>
                              setTouched((current) => ({
                                ...current,
                                [`${product.id}.${key}`]: true,
                              }))
                            }
                          />
                          {error && (
                            <span className="form-field-error" id={`${product.id}-${key}-error`}>
                              {error}
                            </span>
                          )}
                        </td>
                      );
                    })}
                    <td className="product-rotation">
                      <input
                        type="checkbox"
                        checked={product.allow_rotation}
                        disabled={disabled}
                        aria-label={`Разрешить поворот товара ${index + 1}`}
                        onChange={(event) =>
                          update(product.id, { allow_rotation: event.target.checked })
                        }
                      />
                    </td>
                    <td>
                      <div className="product-row-actions">
                        <button
                          className="form-icon-button"
                          type="button"
                          disabled={disabled || products.length >= inputLimits.productTypes}
                          title="Дублировать товар"
                          aria-label={`Дублировать товар ${index + 1}`}
                          onClick={() => add(product)}
                        >
                          <RowActionIcon kind="duplicate" />
                        </button>
                        <button
                          className="form-icon-button danger"
                          type="button"
                          disabled={disabled}
                          title="Удалить товар"
                          aria-label={`Удалить товар ${index + 1}`}
                          onClick={() =>
                            onChange(products.filter((item) => item.id !== product.id))
                          }
                        >
                          <RowActionIcon kind="remove" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="form-empty">
          <strong>Добавьте первый товар</strong>
          <p>Заполните размеры и количество или загрузите демо-заказ.</p>
        </div>
      )}
      {(errors.products ||
        errors['body.products'] ||
        (total > inputLimits.totalItems && validation.products)) && (
        <p className="form-error-banner" role="alert">
          {errors.products ?? errors['body.products'] ?? validation.products}
        </p>
      )}
      <div className="product-editor-footer">
        <button
          className="form-secondary-button"
          type="button"
          disabled={disabled || products.length >= inputLimits.productTypes}
          onClick={() => add()}
        >
          <span aria-hidden="true">＋</span> Добавить товар
        </button>
        <div className="product-editor-meta">
          <span className="form-count">
            {products.length} поз. · {total.toLocaleString('ru-RU')} шт.
          </span>
          <span className="form-helper">Tab — следующее поле · Количество указывается в единицах товара</span>
        </div>
      </div>
    </div>
  );
}
