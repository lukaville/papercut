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
from OCP.gp import gp_Trsf, gp_Vec

from models import Color, PartInstance


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


def _get_matrix(label: TDF_Label) -> gp_Trsf:
    """Extract transformation from a label."""
    loc = XCAFDoc_ShapeTool.GetLocation_s(label)
    return loc.Transformation()


def _combine_trsf(t1: gp_Trsf, t2: gp_Trsf) -> gp_Trsf:
    """Combine two transformations."""
    return t1.Multiplied(t2)


def _trsf_to_list(trsf: gp_Trsf) -> list[float]:
    """Convert gp_Trsf to a 4x4 column-major list of 16 floats for Three.js."""
    m = [0.0] * 16
    # Three.js expects column-major order:
    # m[0] m[4] m[8]  m[12]
    # m[1] m[5] m[9]  m[13]
    # m[2] m[6] m[10] m[14]
    # m[3] m[7] m[11] m[15]
    
    # gp_Trsf represents a 3x4 affine transformation matrix:
    # [ R11 R12 R13 T1 ]
    # [ R21 R22 R23 T2 ]
    # [ R31 R32 R33 T3 ]
    for row in range(1, 4):
        for col in range(1, 5):
            # Map (row, col) to column-major index (col-1)*4 + (row-1)
            m[(col-1)*4 + (row-1)] = trsf.Value(row, col)
            
    m[3], m[7], m[11], m[15] = 0.0, 0.0, 0.0, 1.0
    return m


def _extract_solids_with_metadata(
    doc: TDocStd_Document,
    label: TDF_Label,
    current_trsf: gp_Trsf,
    instances_out: list[PartInstance],
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
    
    # Get local transformation and combine with parent
    local_trsf = _get_matrix(label)
    trsf = _combine_trsf(current_trsf, local_trsf)
    
    t = trsf.TranslationPart()
    
    is_ref = XCAFDoc_ShapeTool.IsReference_s(label)
    is_assembly = XCAFDoc_ShapeTool.IsAssembly_s(label)
    is_component = XCAFDoc_ShapeTool.IsComponent_s(label)

    # If it's a reference, follow it to find the actual shape/assembly
    referred_label = label
    if is_ref:
        ref_label = TDF_Label()
        if XCAFDoc_ShapeTool.GetReferredShape_s(label, ref_label):
            referred_label = ref_label

    # Check if this referred label has a shape
    if XCAFDoc_ShapeTool.IsShape_s(referred_label):
        shape_raw = XCAFDoc_ShapeTool.GetShape_s(referred_label)
        if not shape_raw.IsNull():
            # Process solid(s) from the shape
            solids = []
            if shape_raw.ShapeType() == TopAbs_SOLID:
                solids.append(shape_raw)
            else:
                explorer = TopExp_Explorer(shape_raw, TopAbs_SOLID)
                while explorer.More():
                    solids.append(explorer.Current())
                    explorer.Next()
            
            for s in solids:
                # Use CadQuery's Center to find the world position
                cq_shape = cq.Shape(s)
                com = cq_shape.Center()
                
                # Create a transformation from origin to COM
                com_trsf = gp_Trsf()
                com_trsf.SetTranslation(gp_Vec(com.x, com.y, com.z))
                
                # Combine with any label-level transformation
                combined_trsf = _combine_trsf(trsf, com_trsf)
                
                # The "base" shape for deduplication should be at origin
                # We use translate instead of Location to be more robust with flat files
                base_shape = cq_shape.translate(cq.Vector(com).multiply(-1))
                
                instances_out.append(PartInstance(
                    name=name,
                    color=color,
                    solid=base_shape, 
                    matrix=_trsf_to_list(combined_trsf)
                ))

    # Recurse into children of the referred label (if it's an assembly or has components)
    comps = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetComponents_s(referred_label, comps)
    for i in range(1, comps.Length() + 1):
        _extract_solids_with_metadata(doc, comps.Value(i), trsf, instances_out, visited)
    
    # Also sub-shapes (if they are not components)
    sub_shapes = TDF_LabelSequence()
    XCAFDoc_ShapeTool.GetSubShapes_s(label, sub_shapes)
    for i in range(1, sub_shapes.Length() + 1):
        _extract_solids_with_metadata(doc, sub_shapes.Value(i), trsf, instances_out, visited)


def load_step(path: Path) -> list[PartInstance]:
    """Load a STEP file and return a list of PartInstance objects.

    Uses XDE to preserve part names, colors, and 3D placements.
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

    instances: list[PartInstance] = []
    identity = gp_Trsf()
    for i in range(1, labels.Length() + 1):
        root_label = labels.Value(i)
        _extract_solids_with_metadata(doc, root_label, identity, instances)

    return instances
