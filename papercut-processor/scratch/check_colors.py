import sys
from pathlib import Path
from OCP.TDocStd import TDocStd_Document
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv
from OCP.TDF import TDF_LabelSequence
from OCP.Quantity import Quantity_ColorRGBA

from OCP.TCollection import TCollection_ExtendedString

def check_colors(step_path):
    doc = TDocStd_Document(TCollection_ExtendedString("MD-XCAF"))
    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(str(step_path))
    if status != 1:
        print(f"Error: Cannot read {step_path}")
        return

    reader.Transfer(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    
    print(f"Found {labels.Length()} free shapes")
    
    colors_found = set()
    for i in range(1, labels.Length() + 1):
        label = labels.Value(i)
        
        color = Quantity_ColorRGBA()
        found = False
        if color_tool.GetColor(label, XCAFDoc_ColorGen, color) or \
           color_tool.GetColor(label, XCAFDoc_ColorSurf, color) or \
           color_tool.GetColor(label, XCAFDoc_ColorCurv, color):
            hex_val = f"#{int(color.GetRGB().Red()*255):02x}{int(color.GetRGB().Green()*255):02x}{int(color.GetRGB().Blue()*255):02x}"
            colors_found.add(hex_val)
            found = True
            
        if not found:
            colors_found.add("NONE")

    print(f"Colors found: {colors_found}")

if __name__ == "__main__":
    check_colors(sys.argv[1])
