import ezdxf
from ezdxf.addons.importer import Importer
from pathlib import Path
import sys

def manage_overlays(project_dir: Path, overlay_parts: list[str]) -> None:
    """Manage overlay DXF files for specified parts.
    
    Creates an 'overlays/' directory. For each part, creates/updates a DXF
    that contains an embedded block with the current part geometry.
    Manual drawings on the 'engraving' layer are preserved.
    """
    if not overlay_parts:
        return

    overlays_dir = project_dir / "overlays"
    overlays_dir.mkdir(parents=True, exist_ok=True)

    parts_dir = project_dir / "parts"

    for part_name in overlay_parts:
        overlay_path = overlays_dir / f"{part_name}.dxf"
        part_dxf_path = parts_dir / f"{part_name}.dxf"

        if not part_dxf_path.exists():
            print(f"Warning: Cannot create overlay for '{part_name}', part DXF not found at {part_dxf_path}", file=sys.stderr)
            continue

        if overlay_path.exists():
            _update_overlay(overlay_path, part_dxf_path, part_name)
        else:
            _create_overlay(overlay_path, part_dxf_path, part_name)


def _create_overlay(path: Path, part_path: Path, part_name: str) -> None:
    """Create a new overlay DXF with embedded geometry and engraving layer."""
    doc = ezdxf.new(dxfversion="R2010")
    
    # Add engraving layer
    if "engraving" not in doc.layers:
        doc.layers.add(name="engraving", color=1) # Red
        
    # Create a block for the base geometry
    block_name = "BASE_GEOMETRY"
    block = doc.blocks.new(name=block_name)
    
    # Import part geometry into the block
    _import_geometry(part_path, doc, block)
    
    # Insert the block into modelspace
    doc.modelspace().add_blockref(name=block_name, insert=(0, 0), dxfattribs={'layer': '0'})
    
    doc.saveas(path)
    print(f"  Created new overlay: {path.name}")


def _update_overlay(path: Path, part_path: Path, part_name: str) -> None:
    """Update an existing overlay DXF by replacing the embedded block content."""
    try:
        doc = ezdxf.readfile(path)
        
        # Ensure engraving layer exists
        if "engraving" not in doc.layers:
            doc.layers.add(name="engraving", color=1)

        block_name = "BASE_GEOMETRY"
        if block_name in doc.blocks:
            # Clear existing geometry in the block
            block = doc.blocks.get(block_name)
            block.delete_all_entities()
        else:
            # Create block if missing
            block = doc.blocks.new(name=block_name)
            # And insert it if missing from modelspace
            doc.modelspace().add_blockref(name=block_name, insert=(0, 0), dxfattribs={'layer': '0'})

        # Re-import geometry
        _import_geometry(part_path, doc, block)
        
        doc.save()
        print(f"  Updated geometry in overlay: {path.name}")
    except Exception as e:
        print(f"Error updating overlay {path}: {e}", file=sys.stderr)


def _import_geometry(source_path: Path, target_doc: ezdxf.document.Drawing, target_layout) -> None:
    """Import all entities from modelspace of source_path into target_layout."""
    try:
        source_doc = ezdxf.readfile(source_path)
        importer = Importer(source_doc, target_doc)
        importer.import_modelspace(target_layout)
        importer.finalize()
    except Exception as e:
        print(f"  Failed to import geometry from {source_path.name}: {e}", file=sys.stderr)
