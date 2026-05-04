import ezdxf
from ezdxf.math import Matrix44, Vec3
from overlay_manager import get_engraving_entities
from pathlib import Path

overlay = Path("./projects/khrushchevka/overlays/outer_front.dxf")
part = Path("./projects/khrushchevka/parts/outer_front.dxf")

engravings, mat = get_engraving_entities(overlay, part)
print(f"Matrix: \n{mat}")

test_pt = Vec3(-112.0, 6.0, 0.0) # Bottom-left of overlay
result = mat.transform(test_pt)
print(f"Transform (-112, 6) -> {result}")

test_pt2 = Vec3(112.0, 101.333, 0.0) # Top-right of overlay
result2 = mat.transform(test_pt2)
print(f"Transform (112, 101.333) -> {result2}")
