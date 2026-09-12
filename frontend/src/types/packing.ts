/** Contract v1: docs/CONTRACTS.md. Integer millimetres and grams; volumes in mm³. */
export type Orientation = 'LWH' | 'LHW' | 'WLH' | 'WHL' | 'HLW' | 'HWL';
export type PackingStatus = 'success' | 'partial' | 'impossible';
export type IssueSeverity = 'info' | 'warning' | 'error';
export type IssueCode =
  | 'ITEM_TOO_LARGE'
  | 'ITEM_TOO_HEAVY'
  | 'BOX_STOCK_EXHAUSTED'
  | 'NO_BOX_TYPES'
  | 'NO_FEASIBLE_PLACEMENT'
  | 'PARTIAL_PACKING'
  | 'SIMILAR_ALTERNATIVES'
  | 'DEMO_STUB';

export interface Dimensions {
  length: number;
  width: number;
  height: number;
}

export interface BoxType extends Dimensions {
  id: string;
  name: string;
  max_weight: number;
  available_count: number;
}

export interface Product extends Dimensions {
  id: string;
  name: string;
  weight: number;
  quantity: number;
  allow_rotation: boolean;
}

export interface ItemInstance extends Dimensions {
  id: string;
  product_id: string;
  name: string;
  unit_index: number;
  weight: number;
  allow_rotation: boolean;
}

/** Minimum corner in the box: x right, y toward the back, z up. */
export interface Position {
  x: number;
  y: number;
  z: number;
}

export interface Placement {
  item_instance_id: string;
  product_id: string;
  position: Position;
  dimensions: Dimensions;
  orientation: Orientation;
  step: number;
}

export interface PackingInstructionStep {
  step: number;
  action: 'prepare_box' | 'place_item' | 'close_box';
  box_id: string;
  message: string;
  item_instance_id: string | null;
  product_id: string | null;
  position: Position | null;
  dimensions: Dimensions | null;
  orientation: Orientation | null;
}

export interface PackedBox extends Dimensions {
  id: string;
  box_type_id: string;
  name: string;
  max_weight: number;
  total_weight: number;
  used_volume: number;
  fill_ratio: number;
  placements: Placement[];
  instructions: PackingInstructionStep[];
}

export interface PackingMetrics {
  total_items: number;
  packed_items: number;
  unpacked_items: number;
  boxes_used: number;
  boxes_by_type: Record<string, number>;
  total_box_volume: number;
  used_volume: number;
  empty_volume: number;
  fill_ratio: number;
  total_weight: number;
}

export interface PackingIssue {
  code: IssueCode;
  severity: IssueSeverity;
  message: string;
  item_instance_ids: string[];
  box_type_ids: string[];
}

export interface PackingAlternative {
  id: string;
  description: string;
  status: PackingStatus;
  metrics: PackingMetrics;
  packed_boxes: PackedBox[];
  unpacked_items: ItemInstance[];
  issues: PackingIssue[];
}

export interface PackingOptions {
  include_alternatives?: boolean;
  max_alternatives?: number;
  algorithm?: PackingAlgorithm;
  solver_timeout_ms?: number;
  solver_workers?: number;
}

export type PackingAlgorithm = 'heuristic' | 'z3';

export interface PackingOptimization {
  status: 'optimal' | 'feasible' | 'fallback';
  reason: 'completed' | 'time_limit' | 'size_limit' | 'solver_error';
  workers: number;
  time_limit_ms: number;
  support_ratio: number;
}

export interface PackingRequest {
  boxes: BoxType[];
  products: Product[];
  options?: PackingOptions;
}

export interface PackingResult {
  status: PackingStatus;
  metrics: PackingMetrics;
  packed_boxes: PackedBox[];
  unpacked_items: ItemInstance[];
  issues: PackingIssue[];
  alternatives: PackingAlternative[];
  algorithm_version: string;
  optimization?: PackingOptimization | null;
  calculation_seconds?: number | null;
}

export interface DemoScenario {
  id: string;
  name: string;
  description: string;
  expected_status: PackingStatus;
}

export interface HealthResponse {
  status: 'ok';
  api_version: 'v1';
  engine: string;
}

export type ApiErrorCode =
  | 'HTTP_ERROR'
  | 'METHOD_NOT_ALLOWED'
  | 'VALIDATION_ERROR'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'ENGINE_NOT_IMPLEMENTED'
  | 'INTERNAL_ERROR';

export interface ApiErrorDetail {
  field: string;
  message: string;
  type: string;
}

export interface ApiErrorResponse {
  error: {
    code: ApiErrorCode;
    message: string;
    details: ApiErrorDetail[];
  };
}
