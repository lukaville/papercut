# Papercut: Automated Laser Cutting Pipeline

Automated manufacturing pipeline for converting 3D CAD assemblies (STEP) into nested, color-coded production sheets (DXF) for laser cutting and engraving.

## Project Architecture

- **`step_reader.py`**: Extracts 3D solids, names, and RGBA colors from STEP files using OpenCASCADE (XDE).
- **`deduplicator.py`**: Groups identical parts based on geometric signature (moments of inertia) and color.
- **`thickness.py`**: Automatically detects material thickness from the geometry.
- **`clash_detection.py`**: Enforces zero-clash policy (volumetric intersection checks).
- **`dxf_exporter.py`**: Projects 3D profiles to 2D, aligns bottom-left to `(0,0)`, and exports to DXF.
- **`overlay_manager.py`**: Manages manual engraving details preserved across CAD updates.
- **`placer.py`**: Implements Shelf-Packing (NFDH) for automated nesting onto infinite sheets.
- **`naming.py`**: Resolves stable, unique 3D part names per deduplicated group (shared by the pipeline and the manual exporter).
- **`manual_exporter.py`**: Exports the 3D model (meshes + stable topological vertices + instance placements) consumed by the `manual-builder` app, into `[project]/manual/model/`.
- **`models.py`**: Centralized typed data structures.

## Useful Commands

### Processing a Project
```bash
./process projects/khrushchevka
```
This will:
1. Load `project.yaml` and STEP files.
2. Verify no volumetric clashes.
3. Export unique part DXFs to `parts/`.
4. Update/Create manual engraving templates in `overlays/`.
5. Nest parts onto material-coded sheets in `sheets/`.

### Development
```bash
# Setup environment (requires CadQuery/OCP)
python -m venv .venv
source .venv/bin/activate
pip install -r papercut-processor/requirements.txt
```

## Engineering Practices & Style Guide

### 1. Type Safety
- All shared data structures must be defined in `models.py` using `@dataclass`.
- Avoid untyped dicts or tuples for domain objects.
- Use explicit type hints for all function signatures.

### 2. Unit Clarity
- **Mandatory Suffixes**: All physical dimension properties must include the unit suffix.
- Example: `width_mm`, `area_mm2`, `x_mm`.
- Default unit is always **millimeters**.

### 3. Geometric Consistency
- All exported part DXFs MUST have their absolute minimum coordinates at `(0,0)`.
- Center-of-mass or centered origins are forbidden as they break the nesting algorithm.

### 4. Determinism
- Sheet numbering is global across colors and deterministic.
- Materials are processed in alphabetical order (sorted by hex color string or name).

### 5. Validation
- Fail fast with descriptive errors.
- Enforce strict clash detection (tolerance: 0.0001 mm³).

## Manual Builder Subproject (`manual-builder/`)
A browser-only web app (React + TypeScript + Vite, [caplin/FlexLayout](https://github.com/caplin/FlexLayout) panels, react-three-fiber) for authoring step-by-step assembly manuals.
- **No backend**: project directories are read/written directly via the Chrome File System Access API; the directory handle persists in IndexedDB across refreshes.
- **Data**: reads the generated `[project]/manual/model/` and reads/writes the authored `[project]/manual/manual.json`.
- **Robustness**: anchors on 3D part names (not sheet labels), stable instance ids (`partKey#ordinal`), and vertex indices — so authored manuals survive dimensional CAD changes. See `manual-builder/README.md` for the full format and rationale.
- Run `./process <project>` (or `papercut-processor/export_manual.py`) to (re)generate the model the app consumes.

## Maintenance of Overlays
The `overlays/` directory contains DXF files where the `engraving` layer is intended for manual edits.
- The `BASE_GEOMETRY` block in overlays is automatically updated when the CAD geometry changes.
- Manual drawings on the `engraving` layer are preserved during updates.
- **Registration**: Engravings are relative to the part's bottom-left `(0,0)`.
