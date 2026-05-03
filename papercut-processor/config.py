from pathlib import Path
import yaml
from models import ProjectConfig, FileImport, PartConfig, SheetConfig, PlacementConfig

def load_config(project_dir: Path) -> ProjectConfig:
    """Load and parse project.yaml into a ProjectConfig object."""
    config_path = project_dir / "project.yaml"
    if not config_path.exists():
        return ProjectConfig()

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
        if not data:
            return ProjectConfig()

    # Parse imports
    import_data = data.get("import", [])
    file_imports = []
    for item in import_data:
        file_path = item.get("file")
        if not file_path:
            continue
            
        parts_data = item.get("parts", {})
        parts = {name: PartConfig(flip=p_data.get("flip", False)) 
                 for name, p_data in parts_data.items()}
        file_imports.append(FileImport(file=file_path, parts=parts))
        
    # Parse overlays
    overlay_data = data.get("overlays", [])
    
    # Parse sheets
    sheet_data = []
    for s in data.get("sheets", []):
        sheet_data.append(SheetConfig(
            color=s.get("color", "#000"),
            name=s.get("name", "unnamed"),
            width_mm=float(s.get("width_mm", 0)),
            height_mm=float(s.get("height_mm", 0))
        ))
        
    # Parse placement
    p_data = data.get("placement", {})
    placement = PlacementConfig(
        sheet_margin_mm=float(p_data.get("sheet_margin_mm", 10.0)),
        part_margin_mm=float(p_data.get("part_margin_mm", 5.0)),
        label_square_size_mm=float(p_data.get("label_square_size_mm", 15.0))
    )
    
    return ProjectConfig(
        imports=file_imports, 
        overlays=overlay_data,
        sheets=sheet_data,
        placement=placement
    )
