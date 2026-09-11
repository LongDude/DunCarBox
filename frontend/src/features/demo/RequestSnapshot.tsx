import type { PackingRequest } from '../../types/packing';

export function RequestSnapshot({ request }: { request: PackingRequest }) {
  const quantity = request.products.reduce((total, product) => total + product.quantity, 0);
  return (
    <div className="request-snapshot">
      <div className="section-label">Состав заказа · {quantity} шт.</div>
      <ul className="snapshot-list">
        {request.products.map((product) => (
          <li key={product.id}>
            <div><strong>{product.name}</strong><span>{product.length} × {product.width} × {product.height} мм · {product.weight} г</span></div>
            <span className="quantity">×{product.quantity}</span>
          </li>
        ))}
      </ul>
      <details className="box-stock">
        <summary>Доступные коробки · {request.boxes.length} типа</summary>
        <ul className="snapshot-list">
          {request.boxes.map((box) => (
            <li key={box.id}>
              <div><strong>{box.name}</strong><span>{box.length} × {box.width} × {box.height} мм · до {box.max_weight} г</span></div>
              <span className="quantity">{box.available_count} шт.</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
