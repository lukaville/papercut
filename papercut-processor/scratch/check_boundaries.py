import ezdxf
from pathlib import Path
import sys

def check_sheets(project_dir):
    sheets_dir = Path(project_dir) / "sheets"
    dxf_files = list(sheets_dir.glob("sheet_*.dxf"))
    
    if not dxf_files:
        print("No sheet DXFs found.")
        return

    for sheet_path in dxf_files:
        print(f"\nChecking {sheet_path.name}...")
        doc = ezdxf.readfile(sheet_path)
        msp = doc.modelspace()
        
        # We assume standard A4 for now, but better to get it from the DXF if possible
        # For this project it's 210x297
        width, height = 210.0, 297.0
        
        for entity in msp.query('INSERT'):
            # Get block reference
            insert_pt = entity.dxf.insert
            rotation = entity.dxf.rotation
            block_name = entity.dxf.name
            block = doc.blocks.get(block_name)
            
            # Estimate bounding box of the block
            from ezdxf import bbox
            cache = bbox.Cache()
            box = bbox.extents(entity, cache=cache)
            
            if box.is_empty:
                continue
                
            xmin, ymin, _ = box.extmin
            xmax, ymax, _ = box.extmax
            
            outside = False
            if xmin < -0.01: outside = True
            if ymin < -0.01: outside = True
            if xmax > width + 0.01: outside = True
            if ymax > height + 0.01: outside = True
            
            if outside:
                print(f"  [OUTSIDE] Block {block_name} (ref to {entity.dxf.name}) at {insert_pt}")
                print(f"            BBox: ({xmin:.2f}, {ymin:.2f}) to ({xmax:.2f}, {ymax:.2f})")
            else:
                print(f"  [OK] Block {block_name} BBox: ({xmin:.2f}, {ymin:.2f}) to ({xmax:.2f}, {ymax:.2f})")

if __name__ == "__main__":
    check_sheets(sys.argv[1])
