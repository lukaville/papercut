/**
 * Types for the generated 3D model — the read-only output of the Python
 * `manual_exporter`. See papercut-processor/manual_exporter.py for the producer.
 */

export type Vec3 = [number, number, number];

/** Column-major 4x4 transform (16 floats), Three.js compatible. */
export type Mat4 = number[];

export interface BBox {
  min: Vec3;
  max: Vec3;
}

export interface ModelPartEngraving {
  /** Which face of the flat part carries the engraving. */
  side: "top" | "bottom";
  /** SVG path data of the aligned engraving (in DXF / cut-profile coordinates). */
  svg: string;
  /** Column-major 4x4 mapping 2D DXF coords -> local 3D; null if unavailable. */
  transform: Mat4 | null;
}

/** A unique part geometry (a deduplicated CAD group). */
export interface ModelPart {
  /** Stable anchor: the resolved 3D part name. Never a sheet label. */
  key: string;
  names: string[];
  color: string;
  count: number;
  /** Relative path to the mesh file under `manual/model/`. */
  mesh: string;
  vertexCount: number;
  /** Local-space bounding box of the canonical geometry. */
  bbox: BBox | null;
  /** Engraving overlay, if one was resolved for this part. */
  engraving: ModelPartEngraving | null;
}

/** A physical placement of a part within the assembly. */
export interface ModelInstance {
  /** Stable id `"<partKey>#<ordinal>"`. */
  id: string;
  partKey: string;
  /** Local -> world transform (column-major). */
  matrix: Mat4;
  /** Display-only sheet label (e.g. "A12"); may change between runs. */
  sheet: string | null;
  /** Per-instance engraving side override; falls back to the part's side. */
  engravingSide?: "top" | "bottom";
}

export interface ModelData {
  schemaVersion: number;
  project: string;
  generatedAt: string;
  units: string;
  thickness_mm: number | null;
  bounds: BBox | null;
  parts: ModelPart[];
  instances: ModelInstance[];
}

/** Per-part geometry payload, in local (canonical) coordinates. */
export interface MeshData {
  schemaVersion: number;
  positions: number[];
  indices: number[];
  /** Ordered topological vertices; the index is the stable vertex reference. */
  vertices: Vec3[];
}
