"""STEP file reader using XDE to preserve metadata (names and colors)."""

from pathlib import Path
from typing import Optional

import cadquery as cq
from OCP.TDocStd import TDocStd_Document
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv, XCAFDoc_ShapeTool
from OCP.TDF import TDF_LabelSequence, TDF_Label
from OCP.Quantity import Quantity_ColorRGBA
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID

from models import Color


def _get_name(label: TDF_Label) -> str:
    """Extract name from a label using TDataStd_Name."""
    name_attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
        return str(name_attr.Get().ToExtString())
    return "Unnamed"


def _get_color(label: TDF_Label, color_tool, shape_tool) -> Optional[Color]:
    """Try to find a color associated with this label or its shape."""
    color = Quantity_ColorRGBA()
    
    shape = XCAFDoc_ShapeTool.GetShape_s(label)
    if shape.IsNull():
        return None
        
    found = False
    for ctype in [XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv]:
        if color_tool.GetColor(shape, ctype, color):
            found = True
            break
            
    if found:
        rgb = color.GetRGB()
        return Color(r=rgb.Red(), g=rgb.Green(), b=rgb.Blue(), a=color.Alpha())
    
    return None


def _extract_solids_with_metadata(
    doc: TDocStd_Document,
    label: TDF_Label,
    solids_out: list[tuple[cq.Shape, str, Optional[Color]]],
    visited: Optional[set] = None
):
    """Recursively extract solids and their metadata from XDE document."""
    if visited is None:
        visited = set()

    from OCP.TDF import TDF_Tool
    from OCP.TCollection import TCollection_AsciiString
    entry_str = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry_str)
    label_entry = entry_str.ToCString()
    if label_entry in visited:
        return
    visited.add(label_entry)

    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    # Get name and color for this label
    name = _get_name(label)
    color = _get_color(label, color_tool, shape_tool)

    # Check if this label has a shape
    if XCAFDoc_ShapeTool.IsShape_s(label):
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        if shape.IsNull():
            pass
        elif shape.ShapeType() == TopAbs_SOLID:
            solids_out.append((cq.Shape(shape), name, color))
        else:
            # Explore sub-solids if any (e.g. if this is a compound or shell)
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            while explorer.More():
                solid = explorer.Current()
                solids_out.append((cq.Shape(solid), name, color))
                explorer.Next()

    # Recurse into children (assemblies)
    comps = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(label, comps)
    for i in range(1, comps.Length() + 1):
        _extract_solids_with_metadata(doc, comps.Value(i), solids_out, visited)
    
    # Also sub-shapes (if they are not components)
    sub_shapes = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetSubShapes_s(label, sub_shapes)
    for i in range(1, sub_shapes.Length() + 1):
        _extract_solids_with_metadata(doc, sub_shapes.Value(i), solids_out, visited)


def load_step(path: Path) -> list[tuple[cq.Shape, str, Optional[Color]]]:
    """Load a STEP file and return a list of (solid, name, color) tuples.

    Uses XDE to preserve part names and colors.
    """
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")

    # Create XDE document
    doc = TDocStd_Document(TCollection_ExtendedString("Doc"))
    
    # Read and transfer
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(str(path)) != 1:
        raise ValueError(f"Could not read STEP file: {path}")
    
    reader.Transfer(doc)

    # Find all root shapes
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)

    solids_with_metadata: list[tuple[cq.Shape, str, Optional[Color]]] = []
    for i in range(1, labels.Length() + 1):
        _extract_solids_with_metadata(doc, labels.Value(i), solids_with_metadata)

    return solids_with_metadata
