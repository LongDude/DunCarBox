import { describe, expect, it } from 'vitest';
import type { Orientation, PackedBox, Placement } from '../types/packing';
import {
  boxTransform,
  cameraDistance,
  dimensionsToScene,
  domainToScene,
  getLayers,
  placementFootprint,
  placementTransform,
  productColor,
  sceneScale,
  visiblePlacements,
} from './geometry';

const placement: Placement = {
  item_instance_id: 'tea:1',
  product_id: 'tea',
  step: 1,
  orientation: 'WLH',
  position: { x: 100, y: 60, z: 30 },
  dimensions: { length: 80, width: 120, height: 40 },
};
const box: PackedBox = {
  id: 'box:1',
  box_type_id: 'box',
  name: 'Коробка',
  length: 300,
  width: 200,
  height: 150,
  max_weight: 5000,
  total_weight: 500,
  used_volume: 384000,
  fill_ratio: 0.1,
  placements: [
    placement,
    { ...placement, item_instance_id: 'tea:2', step: 2, position: { x: 0, y: 0, z: 0 } },
  ],
  instructions: [],
};

describe('contract coordinate mapping', () => {
  it('maps domain right, back and up onto Three.js right, negative Z and up', () => {
    expect(domainToScene({ x: 17, y: 42, z: 80 })).toEqual([17, 80, -42]);
    expect(domainToScene({ x: 17, y: 42, z: 80 }, 0.01)).toEqual([0.17, 0.8, -0.42]);
    expect(dimensionsToScene({ length: 17, width: 42, height: 80 })).toEqual([17, 80, 42]);
  });

  it('adds half the oriented dimensions before mapping the minimum corner', () => {
    expect(placementTransform(placement)).toEqual({ center: [140, 50, -120], size: [80, 40, 120] });
  });

  it.each<Orientation>(['LWH', 'LHW', 'WLH', 'WHL', 'HLW', 'HWL'])(
    'never applies orientation %s a second time',
    (orientation) => {
      const alreadyOriented = { ...placement, orientation };
      expect(placementTransform(alreadyOriented)).toEqual(placementTransform(placement));
    },
  );

  it('uses the same normalized origin and scale for box and contents without mutating API data', () => {
    const before = JSON.stringify(box);
    const scale = sceneScale(box);
    expect(scale).toBe(0.02);
    expect(boxTransform(box)).toEqual({ center: [3, 1.5, -2], size: [6, 3, 4] });
    const transform = placementTransform(placement, scale);
    expect(transform.center[0]).toBeCloseTo(2.8);
    expect(transform.center[1]).toBe(1);
    expect(transform.center[2]).toBe(-2.4);
    expect(transform.size).toEqual([1.6, 0.8, 2.4]);
    expect(JSON.stringify(box)).toBe(before);
  });

  it('preserves touching box boundaries after normalization', () => {
    const filling = placementTransform(
      { position: { x: 0, y: 0, z: 0 }, dimensions: box },
      sceneScale(box),
    );
    const bounds = boxTransform(box);
    expect(filling).toEqual(bounds);
    expect(filling.center[0] - filling.size[0] / 2).toBe(0);
    expect(filling.center[1] - filling.size[1] / 2).toBe(0);
    expect(filling.center[2] + filling.size[2] / 2).toBe(0);
  });

  it('keeps framing finite at large dimensions and adapts to a portrait viewport', () => {
    const size = boxTransform({ length: 100000, width: 1, height: 10 }).size;
    expect(Math.max(...size)).toBeCloseTo(6);
    const landscape = cameraDistance(size, 2);
    const portrait = cameraDistance(size, 0.5);
    expect(Number.isFinite(portrait)).toBe(true);
    expect(portrait).toBeGreaterThan(landscape);
    expect(landscape).toBeGreaterThan(Math.hypot(...size) / 2);
  });
});

describe('instruction visibility and layers', () => {
  it('shows empty prepare, cumulative placement operations and full close', () => {
    expect(visiblePlacements(box, 0)).toEqual([]);
    expect(visiblePlacements(box, 1).map((item) => item.item_instance_id)).toEqual(['tea:1']);
    expect(visiblePlacements(box, 2)).toEqual(box.placements);
    expect(visiblePlacements(box, 3)).toEqual(box.placements);
    expect(visiblePlacements(box, 0, true)).toEqual(box.placements);
    expect(visiblePlacements(box, -1)).toEqual([]);
  });

  it('groups by exact base height in ascending order without changing placements', () => {
    expect(
      getLayers({ ...box, placements: [...box.placements, { ...placement, step: 3 }] }),
    ).toEqual([0, 30]);
    expect(getLayers({ ...box, placements: [] })).toEqual([]);
    expect(box.placements[0]).toBe(placement);
  });

  it('puts the front edge at the bottom in top view and preserves footprint dimensions', () => {
    expect(placementFootprint(placement, box)).toEqual({ x: 100, y: 20, width: 80, height: 120 });
    expect(placementFootprint({ ...placement, position: { x: 0, y: 0, z: 0 } }, box).y).toBe(80);
  });

  it('keeps product colors stable independent of traversal order', () => {
    const ids = ['tea', 'speaker', 'gift', 'cable'];
    const first = Object.fromEntries(ids.map((id) => [id, productColor(id)]));
    const second = Object.fromEntries([...ids].reverse().map((id) => [id, productColor(id)]));
    expect(first).toEqual(second);
    expect(new Set(Object.values(first)).size).toBeGreaterThan(1);
    expect(productColor('tea')).toMatch(/^#[0-9a-f]{6}$/);
  });
});
