import {
  Component,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import {
  BoxGeometry,
  Color,
  EdgesGeometry,
  InstancedMesh,
  Object3D,
  PerspectiveCamera,
  Vector3,
} from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { PackedBox, Placement, Product } from '../types/packing';
import {
  boxTransform,
  cameraDistance,
  domainToScene,
  getLayers,
  placementFootprint,
  placementTransform,
  productColor,
  sceneScale,
  visiblePlacements,
} from './geometry';
import type { VectorTuple } from './geometry';
import './viewer.css';

export interface PackingViewerProps {
  box: PackedBox;
  step: number;
  showAll: boolean;
  products: Product[];
}

// One shared unit geometry for every instance; step changes only update matrices.
const unitBox = new BoxGeometry(1, 1, 1);
const unitEdges = new EdgesGeometry(unitBox);

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2');
    if (!context) return false;
    context.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

class CanvasBoundary extends Component<
  { children: ReactNode; onUnavailable: () => void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onUnavailable();
  }
  render() {
    return this.state.failed ? (
      <div className="viewer-loading">Открываем вид по слоям…</div>
    ) : (
      this.props.children
    );
  }
}

function CameraRig({
  box,
  reset,
  onUnavailable,
}: {
  box: PackedBox;
  reset: number;
  onUnavailable: () => void;
}) {
  const { camera, gl, size, invalidate } = useThree();
  const controls = useRef<OrbitControls | null>(null);

  useEffect(() => {
    const orbit = new OrbitControls(camera, gl.domElement);
    orbit.enableDamping = false;
    orbit.maxPolarAngle = Math.PI / 2 - 0.015;
    orbit.minDistance = 0.2;
    const onChange = () => invalidate();
    orbit.addEventListener('change', onChange);
    controls.current = orbit;
    const onLost = (event: Event) => {
      event.preventDefault();
      onUnavailable();
    };
    gl.domElement.addEventListener('webglcontextlost', onLost);
    return () => {
      orbit.removeEventListener('change', onChange);
      orbit.dispose();
      controls.current = null;
      gl.domElement.removeEventListener('webglcontextlost', onLost);
    };
  }, [camera, gl, invalidate, onUnavailable]);

  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) return;
    const bounds = boxTransform(box);
    const target = new Vector3(...bounds.center);
    const distance = cameraDistance(bounds.size, size.width / Math.max(size.height, 1), camera.fov);
    camera.position
      .copy(target)
      .add(new Vector3(1, 0.88, 1.2).normalize().multiplyScalar(distance));
    camera.near = 0.01;
    camera.far = Math.max(distance * 12, 100);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.copy(target);
      controls.current.maxDistance = distance * 4;
      controls.current.update();
    }
    invalidate();
  }, [
    box.id,
    box.length,
    box.width,
    box.height,
    camera,
    invalidate,
    reset,
    size.width,
    size.height,
  ]);

  return null;
}

function Outline({
  center,
  size,
  current = false,
}: {
  center: VectorTuple;
  size: VectorTuple;
  current?: boolean;
}) {
  return (
    <group position={center} scale={size} dispose={null}>
      {current && (
        <lineSegments geometry={unitEdges} scale={1.035} renderOrder={3}>
          <lineBasicMaterial color="#fffaf1" depthTest={false} transparent opacity={0.95} />
        </lineSegments>
      )}
      <lineSegments geometry={unitEdges} scale={current ? 1.012 : 1} renderOrder={current ? 4 : 1}>
        <lineBasicMaterial
          color={current ? '#193d35' : '#708b80'}
          transparent
          opacity={current ? 1 : 0.58}
          depthTest={!current}
        />
      </lineSegments>
    </group>
  );
}

function PackedItems({
  box,
  placements,
  scale,
  onSelect,
}: {
  box: PackedBox;
  placements: Placement[];
  scale: number;
  onSelect: (id: string) => void;
}) {
  const mesh = useRef<InstancedMesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const edgePositions = useMemo(() => {
    const unitPositions = unitEdges.getAttribute('position');
    const positions = new Float32Array(placements.length * unitPositions.count * 3);
    placements.forEach((placement, itemIndex) => {
      const transform = placementTransform(placement, scale);
      for (let index = 0; index < unitPositions.count; index += 1) {
        const offset = (itemIndex * unitPositions.count + index) * 3;
        positions[offset] = transform.center[0] + unitPositions.getX(index) * transform.size[0];
        positions[offset + 1] = transform.center[1] + unitPositions.getY(index) * transform.size[1];
        positions[offset + 2] = transform.center[2] + unitPositions.getZ(index) * transform.size[2];
      }
    });
    return positions;
  }, [placements, scale]);
  useLayoutEffect(() => {
    if (!mesh.current) return;
    const object = new Object3D();
    const color = new Color();
    placements.forEach((placement, index) => {
      const transform = placementTransform(placement, scale);
      object.position.set(...transform.center);
      object.scale.set(...transform.size);
      object.updateMatrix();
      mesh.current!.setMatrixAt(index, object.matrix);
      mesh.current!.setColorAt(index, color.set(productColor(placement.product_id)));
    });
    mesh.current.count = placements.length;
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true;
    mesh.current.computeBoundingSphere();
    invalidate();
  }, [placements, scale, invalidate]);

  return (
    <>
      <instancedMesh
        ref={mesh}
        args={[unitBox, undefined, Math.max(1, box.placements.length)]}
        dispose={null}
        onClick={(event) => {
          if (event.instanceId === undefined || !placements[event.instanceId]) return;
          event.stopPropagation();
          onSelect(placements[event.instanceId].item_instance_id);
        }}
      >
        <meshStandardMaterial roughness={0.75} metalness={0.02} />
      </instancedMesh>
      {placements.length > 0 && (
        <lineSegments>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[edgePositions, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color="#344e40" transparent opacity={0.42} />
        </lineSegments>
      )}
    </>
  );
}

function Scene({
  box,
  placements,
  current,
  selected,
  reset,
  onSelect,
  onUnavailable,
}: {
  box: PackedBox;
  placements: Placement[];
  current?: Placement;
  selected?: Placement;
  reset: number;
  onSelect: (id: string) => void;
  onUnavailable: () => void;
}) {
  const scale = sceneScale(box);
  const bounds = boxTransform(box, scale);
  const floor = domainToScene({ x: box.length / 2, y: box.width / 2, z: 0 }, scale);
  const front = domainToScene({ x: box.length / 2, y: 0, z: 0 }, scale);
  return (
    <>
      <color attach="background" args={['#f2f5ef']} />
      <ambientLight intensity={1.6} />
      <directionalLight position={[4, 9, 6]} intensity={2.2} />
      <directionalLight position={[-4, 3, -3]} intensity={0.6} />
      <mesh
        position={[floor[0], -0.024, floor[2]]}
        geometry={unitBox}
        scale={[bounds.size[0], 0.035, bounds.size[2]]}
        dispose={null}
      >
        <meshStandardMaterial color="#d7dfcf" roughness={1} />
      </mesh>
      <mesh
        position={front}
        geometry={unitBox}
        scale={[bounds.size[0], 0.035, 0.035]}
        dispose={null}
      >
        <meshBasicMaterial color="#25684f" />
      </mesh>
      <Outline {...bounds} />
      <PackedItems box={box} placements={placements} scale={scale} onSelect={onSelect} />
      {current && <Outline {...placementTransform(current, scale)} current />}
      {selected && selected.item_instance_id !== current?.item_instance_id && (
        <Outline {...placementTransform(selected, scale)} current />
      )}
      <CameraRig box={box} reset={reset} onUnavailable={onUnavailable} />
    </>
  );
}

function LayerView({
  box,
  placements,
  layer,
  current,
  selected,
  productNames,
  onSelect,
}: {
  box: PackedBox;
  placements: Placement[];
  layer: number;
  current?: Placement;
  selected?: Placement;
  productNames: Map<string, string>;
  onSelect: (id: string) => void;
}) {
  const visible = placements.filter((placement) => placement.position.z === layer);
  const stroke = Math.max(box.length, box.width) / 220;
  return (
    <div className="viewer-layer">
      <span className="viewer-layer-edge">Дальняя сторона</span>
      <svg
        viewBox={`${-stroke * 2} ${-stroke * 2} ${box.length + stroke * 4} ${box.width + stroke * 4}`}
        aria-label={`Вид сверху, основание слоя на высоте ${layer} мм`}
        role="group"
      >
        <rect
          width={box.length}
          height={box.width}
          fill="#e5eadf"
          stroke="#8a9b8c"
          strokeWidth={stroke}
        />
        {visible.map((placement) => {
          const footprint = placementFootprint(placement, box);
          const isCurrent = current?.item_instance_id === placement.item_instance_id;
          const isSelected = selected?.item_instance_id === placement.item_instance_id;
          const name = productNames.get(placement.product_id) ?? placement.product_id;
          return (
            <g
              key={placement.item_instance_id}
              tabIndex={0}
              role="button"
              aria-label={`${name}, ${placement.item_instance_id}, шаг ${placement.step}${isCurrent ? ', текущий товар' : ''}`}
              onClick={() => onSelect(placement.item_instance_id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(placement.item_instance_id);
                }
              }}
            >
              <title>{`${name} · ${placement.dimensions.length} × ${placement.dimensions.width} × ${placement.dimensions.height} мм · шаг ${placement.step}`}</title>
              <rect
                {...footprint}
                fill={productColor(placement.product_id)}
                stroke={isCurrent || isSelected ? '#173d32' : '#f8faf5'}
                strokeWidth={stroke * (isCurrent || isSelected ? 2.5 : 0.8)}
              />
              {(isCurrent || isSelected) && (
                <rect
                  x={footprint.x + stroke * 3}
                  y={footprint.y + stroke * 3}
                  width={Math.max(0, footprint.width - stroke * 6)}
                  height={Math.max(0, footprint.height - stroke * 6)}
                  fill="none"
                  stroke="#fff"
                  strokeWidth={stroke}
                  strokeDasharray={`${stroke * 3} ${stroke * 2}`}
                />
              )}
              {Math.min(footprint.width, footprint.height) > stroke * 8 && (
                <text
                  x={footprint.x + footprint.width / 2}
                  y={footprint.y + footprint.height / 2}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="#122e29"
                  fontWeight={700}
                  fontSize={Math.min(stroke * 7, footprint.width / 3, footprint.height / 3)}
                >
                  {placement.step}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={0}
          x2={box.length}
          y1={box.width}
          y2={box.width}
          stroke="#25684f"
          strokeWidth={stroke * 2}
        />
      </svg>
      <span className="viewer-layer-edge viewer-front-edge">Передняя сторона · вы здесь</span>
      {!visible.length && <p className="viewer-layer-empty">На этом шаге слой пуст.</p>}
    </div>
  );
}

export default function PackingViewer({ box, step, showAll, products }: PackingViewerProps) {
  const [mode, setMode] = useState<'3d' | 'layers'>('3d');
  const [webgl, setWebgl] = useState<boolean | null>(null);
  const [reset, setReset] = useState(0);
  const [chosenLayer, setChosenLayer] = useState<{ context: string; height: number } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const unavailable = useCallback(() => setWebgl(false), []);
  useEffect(() => {
    setWebgl(hasWebGL());
  }, []);
  useEffect(() => {
    setSelectedId(null);
  }, [box.id, step, showAll]);

  const placements = useMemo(() => visiblePlacements(box, step, showAll), [box, step, showAll]);
  const layers = useMemo(() => getLayers(box), [box]);
  const productNames = useMemo(
    () => new Map(products.map((product) => [product.id, product.name])),
    [products],
  );
  const current = showAll ? undefined : placements.find((placement) => placement.step === step);
  const selected = placements.find((placement) => placement.item_instance_id === selectedId);
  const context = `${box.id}:${step}:${showAll}`;
  const layer =
    chosenLayer?.context === context && layers.includes(chosenLayer.height)
      ? chosenLayer.height
      : (current?.position.z ?? layers[0] ?? 0);
  const usingLayers = mode === 'layers' || webgl === false;
  const legend = useMemo(() => {
    const counts = new Map<string, number>();
    box.placements.forEach((placement) =>
      counts.set(placement.product_id, (counts.get(placement.product_id) ?? 0) + 1),
    );
    return [...counts];
  }, [box]);
  const describe = (placement: Placement) =>
    productNames.get(placement.product_id) ?? placement.product_id;

  return (
    <section className="packing-viewer" aria-label="Схема укладки в коробку">
      <div className="viewer-toolbar">
        <div className="viewer-modes" role="group" aria-label="Режим схемы">
          <button
            type="button"
            aria-pressed={!usingLayers}
            disabled={webgl === false}
            onClick={() => setMode('3d')}
          >
            3D
          </button>
          <button type="button" aria-pressed={usingLayers} onClick={() => setMode('layers')}>
            По слоям
          </button>
        </div>
        {usingLayers ? (
          <label className="viewer-layer-select">
            Слой
            <select
              value={layer}
              disabled={!layers.length}
              onChange={(event) => setChosenLayer({ context, height: Number(event.target.value) })}
            >
              {layers.length ? (
                layers.map((height, index) => (
                  <option key={height} value={height}>
                    {index + 1} из {layers.length} · {height} мм
                  </option>
                ))
              ) : (
                <option value={0}>Дно · 0 мм</option>
              )}
            </select>
          </label>
        ) : (
          <button
            className="viewer-reset"
            type="button"
            onClick={() => setReset((value) => value + 1)}
            aria-label="Вернуть камеру к исходному виду"
          >
            ↺ Сбросить вид
          </button>
        )}
      </div>

      {webgl === false && (
        <p className="viewer-fallback" role="status">
          3D недоступен в этом браузере. Укладка показана сверху по слоям; все шаги доступны.
        </p>
      )}

      <div className="viewer-viewport">
        <div className="viewer-scene-label" aria-live="polite">
          <span className="viewer-scene-dot" />
          {showAll
            ? 'Вся укладка'
            : current
              ? `Шаг ${step} · ${describe(current)}`
              : step === 0
                ? 'Подготовьте пустую коробку'
                : 'Все товары уложены'}
        </div>
        {usingLayers ? (
          <LayerView
            box={box}
            placements={placements}
            layer={layer}
            current={current}
            selected={selected}
            productNames={productNames}
            onSelect={setSelectedId}
          />
        ) : webgl === null ? (
          <div className="viewer-loading" role="status">
            Подготавливаем 3D-схему…
          </div>
        ) : (
          <CanvasBoundary onUnavailable={unavailable}>
            <Canvas
              frameloop="demand"
              dpr={[1, 1.75]}
              camera={{ fov: 42, near: 0.01, far: 100 }}
              gl={{ antialias: true, alpha: false, powerPreference: 'low-power' }}
              role="img"
              aria-label={`Трёхмерная схема: ${box.name}, показано товаров ${placements.length}. Для клавиатуры используйте вид по слоям.`}
              onPointerMissed={() => setSelectedId(null)}
            >
              <Scene
                box={box}
                placements={placements}
                current={current}
                selected={selected}
                reset={reset}
                onSelect={setSelectedId}
                onUnavailable={unavailable}
              />
            </Canvas>
          </CanvasBoundary>
        )}
        {!usingLayers && (
          <div className="viewer-canvas-hint">
            <span>Зелёная грань — передняя сторона</span>
            <span>Тяните для поворота · колесо для масштаба</span>
          </div>
        )}
      </div>

      <div className="viewer-caption" aria-live="polite">
        {current ? (
          <>
            <strong>
              {usingLayers && current.position.z !== layer
                ? `Текущий товар — на слое ${layers.indexOf(current.position.z) + 1}.`
                : 'Текущий товар выделен контуром.'}
            </strong>{' '}
            {describe(current)} · экземпляр {current.item_instance_id.split(':').at(-1)}.
          </>
        ) : (
          <>
            <strong>
              {showAll
                ? usingLayers
                  ? 'Все шаги доступны по слоям.'
                  : 'Показана вся укладка.'
                : step === 0
                  ? 'Коробка пока пуста.'
                  : 'Укладка завершена.'}
            </strong>{' '}
            {usingLayers ? 'Уложено' : 'Видно'} {placements.length} из {box.placements.length}{' '}
            товаров.
          </>
        )}
        {usingLayers && (
          <span>
            {' '}
            На этом слое: {
              placements.filter((placement) => placement.position.z === layer).length
            }{' '}
            товаров с основанием на высоте {layer} мм. Цифры — шаги укладки.
          </span>
        )}
      </div>

      <div className="viewer-legend" aria-label="Товары и цвета на схеме">
        {legend.map(([id, count]) => {
          const visible = placements.find((placement) => placement.product_id === id);
          return (
            <button
              key={id}
              type="button"
              disabled={!visible}
              title={visible ? 'Выделить товар на схеме' : 'Товар появится на следующих шагах'}
              aria-pressed={selected?.product_id === id}
              onClick={() => {
                if (!visible) return;
                setSelectedId(selected?.product_id === id ? null : visible.item_instance_id);
                if (usingLayers) setChosenLayer({ context, height: visible.position.z });
              }}
            >
              <span className="viewer-swatch" style={{ backgroundColor: productColor(id) }} />
              <span>{productNames.get(id) ?? id}</span>
              <b>{count}</b>
            </button>
          );
        })}
      </div>
      {selected && (
        <div className="viewer-inspection">
          <span>
            <strong>Осмотр: {describe(selected)}</strong> · экземпляр{' '}
            {selected.item_instance_id.split(':').at(-1)} · {selected.dimensions.length} ×{' '}
            {selected.dimensions.width} × {selected.dimensions.height} мм · шаг {selected.step}
          </span>
          <button
            type="button"
            aria-label="Снять выделение товара"
            onClick={() => setSelectedId(null)}
          >
            ×
          </button>
        </div>
      )}
    </section>
  );
}
