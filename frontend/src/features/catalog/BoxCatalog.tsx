import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, toApiError } from '../../api/client';
import { inputLimits, validateBox } from '../../api/validation';
import { BoxIcon } from '../../components/BoxIcon';
import type { BoxType } from '../../types/packing';
import '../order/forms.css';

export { validateBox };

interface BoxCatalogProps {
  boxes: BoxType[];
  loading: boolean;
  error: ApiError | null;
  onReload: () => void;
  onCreate: (box: BoxType) => Promise<void>;
  onUpdate: (box: BoxType) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

type BoxNumericField = 'length' | 'width' | 'height' | 'max_weight' | 'available_count';
const numericFields: { key: BoxNumericField; label: string; min: number; max: number }[] = [
  { key: 'length', label: 'Длина, мм', min: 1, max: inputLimits.dimension },
  { key: 'width', label: 'Ширина, мм', min: 1, max: inputLimits.dimension },
  { key: 'height', label: 'Высота, мм', min: 1, max: inputLimits.dimension },
  { key: 'max_weight', label: 'Максимальный вес, г', min: 1, max: inputLimits.weight },
  { key: 'available_count', label: 'В наличии, шт.', min: 0, max: inputLimits.boxCount },
];

function newBox(boxes: BoxType[]): BoxType {
  let index = 1;
  while (boxes.some((box) => box.id === `box-${index}`)) index += 1;
  return {
    id: `box-${index}`,
    name: '',
    length: Number.NaN,
    width: Number.NaN,
    height: Number.NaN,
    max_weight: Number.NaN,
    available_count: 1,
  };
}

export function BoxCatalog({
  boxes,
  loading,
  error,
  onReload,
  onCreate,
  onUpdate,
  onDelete,
}: BoxCatalogProps) {
  const [draft, setDraft] = useState<BoxType | null>(null);
  const [editing, setEditing] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const openEditor = (box?: BoxType) => {
    setDraft(box ? { ...box } : newBox(boxes));
    setEditing(!!box);
    setErrors({});
    setMutationError(null);
    setDeletingId(null);
    requestAnimationFrame(() =>
      formRef.current?.querySelector<HTMLInputElement>('[name="name"]')?.focus(),
    );
  };

  const closeEditor = () => {
    setDraft(null);
    setErrors({});
    setMutationError(null);
    addButtonRef.current?.focus();
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft || pendingRef.current) return;
    const validation = validateBox(draft);
    if (!editing && boxes.some((box) => box.id === draft.id))
      validation.id = 'Коробка с таким кодом уже есть. Укажите другой код.';
    if (!editing && boxes.length >= inputLimits.boxTypes)
      validation.id = 'В каталоге может быть не более 100 типов коробок.';
    setErrors(validation);
    if (Object.keys(validation).length > 0) {
      const field = Object.keys(validation)[0];
      formRef.current?.querySelector<HTMLInputElement>(`[name="${field}"]`)?.focus();
      return;
    }
    setMutationError(null);
    pendingRef.current = true;
    setPending(true);
    try {
      const box = { ...draft, name: draft.name.trim() };
      await (editing ? onUpdate(box) : onCreate(box));
      setAnnouncement(`Коробка «${box.name}» ${editing ? 'обновлена' : 'добавлена'}.`);
      closeEditor();
    } catch (cause: unknown) {
      const failure = toApiError(cause);
      setMutationError(failure.message);
      const serverErrors: Record<string, string> = {};
      failure.details.forEach((detail) => {
        const field = detail.field.replace(/^body\./, '');
        if (field in draft) serverErrors[field] = 'Проверьте значение: сервис отклонил это поле.';
      });
      if (failure.code === 'CONFLICT') serverErrors.id = 'Этот код уже занят. Укажите другой код.';
      setErrors(serverErrors);
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  const remove = async (box: BoxType) => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setMutationError(null);
    try {
      await onDelete(box.id);
      setDeletingId(null);
      setAnnouncement(`Коробка «${box.name}» удалена.`);
      addButtonRef.current?.focus();
    } catch (cause: unknown) {
      setMutationError(toApiError(cause).message);
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };

  return (
    <section className="catalog" aria-labelledby="catalog-title" aria-busy={loading || pending}>
      <div className="form-section-heading">
        <div>
          <h2 id="catalog-title">Каталог коробок</h2>
          <p>Внутренние размеры и доступный остаток на складе.</p>
        </div>
        <button
          ref={addButtonRef}
          className="form-secondary-button"
          type="button"
          disabled={loading || pending || boxes.length >= inputLimits.boxTypes}
          onClick={() => openEditor()}
        >
          <span aria-hidden="true">＋</span> Добавить коробку
        </button>
      </div>
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {error && (
        <div className="form-error-banner" role="alert">
          <p>{error.message}</p>
          <button className="form-text-button" type="button" disabled={loading} onClick={onReload}>
            Повторить загрузку
          </button>
        </div>
      )}
      {mutationError && (
        <p className="form-error-banner" role="alert">
          {mutationError}
        </p>
      )}
      {draft && (
        <form
          className="catalog-editor"
          ref={formRef}
          onSubmit={(event) => void save(event)}
          noValidate
          aria-labelledby="box-editor-title"
        >
          <h3 id="box-editor-title">{editing ? 'Изменить коробку' : 'Новая коробка'}</h3>
          <p className="form-helper">
            Укажите внутренние размеры. Вес — допустимая суммарная масса товаров без тары.
          </p>
          <fieldset disabled={pending}>
            <div className="catalog-form-grid">
              <label className="catalog-name-field">
                Название
                <input
                  name="name"
                  type="text"
                  value={draft.name}
                  required
                  maxLength={200}
                  placeholder="Например, Коробка M"
                  aria-invalid={!!errors.name}
                  aria-describedby={errors.name ? 'box-name-error' : undefined}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
                {errors.name && (
                  <span className="form-field-error" id="box-name-error">
                    {errors.name}
                  </span>
                )}
              </label>
              <label>
                Код коробки
                <input
                  name="id"
                  type="text"
                  value={draft.id}
                  required
                  maxLength={64}
                  pattern="[A-Za-z0-9][A-Za-z0-9_\-]{0,63}"
                  readOnly={editing}
                  aria-invalid={!!errors.id}
                  aria-describedby={errors.id ? 'box-id-error' : 'box-id-hint'}
                  onChange={(event) => setDraft({ ...draft, id: event.target.value })}
                />
                {errors.id ? (
                  <span className="form-field-error" id="box-id-error">
                    {errors.id}
                  </span>
                ) : (
                  <span className="form-helper" id="box-id-hint">
                    {editing
                      ? 'Код сохранённой коробки не меняется.'
                      : 'Уникальный код латинскими буквами.'}
                  </span>
                )}
              </label>
              {numericFields.map(({ key, label, min, max }) => (
                <label key={key}>
                  {label}
                  <input
                    name={key}
                    type="number"
                    required
                    min={min}
                    max={max}
                    step={1}
                    inputMode="numeric"
                    value={Number.isFinite(draft[key]) ? draft[key] : ''}
                    placeholder="—"
                    aria-invalid={!!errors[key]}
                    aria-describedby={errors[key] ? `box-${key}-error` : undefined}
                    onChange={(event) => setDraft({ ...draft, [key]: event.target.valueAsNumber })}
                  />
                  {errors[key] && (
                    <span className="form-field-error" id={`box-${key}-error`}>
                      {errors[key]}
                    </span>
                  )}
                </label>
              ))}
            </div>
            <div className="catalog-editor-actions">
              <button className="form-primary-button" type="submit">
                {pending ? 'Сохраняем…' : 'Сохранить коробку'}
              </button>
              <button className="form-secondary-button" type="button" onClick={closeEditor}>
                Отмена
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {loading ? (
        <div className="catalog-loading" role="status">
          <span className="spinner" aria-hidden="true" />
          Загружаем коробки…
        </div>
      ) : boxes.length === 0 && !error ? (
        <div className="form-empty">
          <BoxIcon />
          <strong>В каталоге пока нет коробок</strong>
          <p>Добавьте тип коробки, чтобы использовать его при расчёте.</p>
        </div>
      ) : (
        <div className="catalog-grid">
          {boxes.map((box) => (
            <article
              className={`catalog-card${box.available_count === 0 ? ' no-stock' : ''}`}
              key={box.id}
            >
              <div className="catalog-card-top">
                <div className="catalog-box-icon">
                  <BoxIcon />
                </div>
                <span className={`catalog-stock${box.available_count === 0 ? ' empty' : ''}`}>
                  {box.available_count === 0
                    ? 'Нет в наличии'
                    : `${box.available_count.toLocaleString('ru-RU')} шт. в наличии`}
                </span>
              </div>
              <h3>{box.name}</h3>
              <p className="catalog-code">{box.id}</p>
              <p className="catalog-dimensions">
                {box.length.toLocaleString('ru-RU')} × {box.width.toLocaleString('ru-RU')} ×{' '}
                {box.height.toLocaleString('ru-RU')} <span>мм</span>
              </p>
              <p className="form-helper">
                Длина × ширина × высота · до {box.max_weight.toLocaleString('ru-RU')} г
              </p>
              {deletingId === box.id ? (
                <div
                  className="catalog-delete-confirm"
                  role="group"
                  aria-label={`Подтверждение удаления ${box.name}`}
                >
                  <p>Удалить «{box.name}» из каталога?</p>
                  <div>
                    <button
                      className="form-danger-button"
                      type="button"
                      disabled={pending}
                      onClick={() => void remove(box)}
                    >
                      {pending ? 'Удаляем…' : 'Да, удалить'}
                    </button>
                    <button
                      className="form-text-button"
                      type="button"
                      disabled={pending}
                      onClick={() => {
                        setDeletingId(null);
                        setMutationError(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <div className="catalog-card-actions">
                  <button
                    className="form-text-button"
                    type="button"
                    disabled={pending}
                    aria-label={`Изменить коробку ${box.name}`}
                    onClick={() => openEditor(box)}
                  >
                    Изменить
                  </button>
                  <button
                    className="form-text-button danger"
                    type="button"
                    disabled={pending}
                    aria-label={`Удалить коробку ${box.name}`}
                    onClick={() => {
                      setDeletingId(box.id);
                      setDraft(null);
                      setMutationError(null);
                    }}
                  >
                    Удалить
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      <p className="catalog-footnote">
        Расчёт использует текущий остаток и не списывает коробки со склада. Нулевой остаток
        сохраняется в каталоге.
      </p>
    </section>
  );
}
