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

## Maintenance of Overlays
The `overlays/` directory contains DXF files where the `engraving` layer is intended for manual edits.
- The `BASE_GEOMETRY` block in overlays is automatically updated when the CAD geometry changes.
- Manual drawings on the `engraving` layer are preserved during updates.
- **Registration**: Engravings are relative to the part's bottom-left `(0,0)`.
