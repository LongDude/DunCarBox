import type { Dimensions, PackedBox, Placement, Position } from '../types/packing';

export type VectorTuple = [number, number, number];

/** Keep the largest box side at six scene units. API values remain integer mm. */
export function sceneScale(box: Dimensions): number {
  return 6 / Math.max(1, box.length, box.width, box.height);
}

/**
 * The only domain → Three.js axis mapping: (x, y, z) → (x, z, -y).
 * Domain origin is the front-left-bottom corner; Three.js has Y pointing up.
 * Scaling happens only at the rendering boundary and never changes the DTO.
 */
export function domainToScene({ x, y, z }: Position, scale = 1): VectorTuple {
  return [x * scale, z * scale, -y * scale];
}

export function dimensionsToScene(dimensions: Dimensions, scale = 1): VectorTuple {
  const mapped = domainToScene(
    { x: dimensions.length, y: dimensions.width, z: dimensions.height },
    scale,
  );
  return [mapped[0], mapped[1], Math.abs(mapped[2])];
}

export function placementTransform(
  placement: Pick<Placement, 'position' | 'dimensions'>,
  scale = 1,
) {
  const { position, dimensions } = placement;
  // dimensions are already oriented by the engine: never apply orientation again.
  return {
    center: domainToScene(
      {
        x: position.x + dimensions.length / 2,
        y: position.y + dimensions.width / 2,
        z: position.z + dimensions.height / 2,
      },
      scale,
    ),
    size: dimensionsToScene(dimensions, scale),
  };
}

export function boxTransform(box: Dimensions, scale = sceneScale(box)) {
  return placementTransform({ position: { x: 0, y: 0, z: 0 }, dimensions: box }, scale);
}

/** Explicit overview overrides step mode; otherwise prepare is empty and close is full. */
export function visiblePlacements(box: PackedBox, step: number, showAll = false): Placement[] {
  return box.placements.filter((placement) => showAll || (step > 0 && placement.step <= step));
}

/** MVP layers group equal base heights, not arbitrary volume intersections. */
export function getLayers(box: PackedBox): number[] {
  return [...new Set(box.placements.map((placement) => placement.position.z))].sort(
    (a, b) => a - b,
  );
}

/** Front is at the bottom of the top-view SVG, consistent with the 3D scene. */
export function placementFootprint(placement: Placement, box: Dimensions) {
  return {
    x: placement.position.x,
    y: box.width - placement.position.y - placement.dimensions.width,
    width: placement.dimensions.length,
    height: placement.dimensions.width,
  };
}

/** A bounding sphere fits even long/thin boxes and portrait viewports. */
export function cameraDistance(size: VectorTuple, aspect: number, verticalFov = 42): number {
  const verticalHalfAngle = (verticalFov * Math.PI) / 360;
  const horizontalHalfAngle = Math.atan(Math.tan(verticalHalfAngle) * Math.max(aspect, 0.01));
  const limitingAngle = Math.min(verticalHalfAngle, horizontalHalfAngle);
  return (Math.hypot(...size) / 2 / Math.sin(limitingAngle)) * 1.15;
}

const PRODUCT_COLORS = [
  '#409b91',
  '#caa252',
  '#738bbf',
  '#bf829e',
  '#8da96a',
  '#c8845e',
  '#8d83b5',
  '#669bac',
];

/** Stable ID hash: colors do not depend on input order, box, or plan selection. */
export function productColor(productId: string): string {
  let hash = 2166136261;
  for (let index = 0; index < productId.length; index += 1) {
    hash = Math.imul(hash ^ productId.charCodeAt(index), 16777619);
  }
  return PRODUCT_COLORS[(hash >>> 0) % PRODUCT_COLORS.length];
}
