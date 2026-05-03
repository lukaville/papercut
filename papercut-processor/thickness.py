"""Material thickness detection for flat laser-cut parts."""

import cadquery as cq


def _bounding_box_dimensions(solid: cq.Shape) -> tuple[float, float, float]:
    """Return the (xSize, ySize, zSize) of a solid's bounding box."""
    bb = solid.BoundingBox()
    return (bb.xlen, bb.ylen, bb.zlen)


def detect_thickness(solids: list[cq.Shape]) -> float:
    """Detect material thickness from the largest part.

    For flat laser-cut parts, the smallest bounding box dimension
    of the largest part (by volume) corresponds to the material thickness.
    """
    if not solids:
        raise ValueError("No solids provided for thickness detection")

    largest = max(solids, key=lambda s: s.Volume())
    dims = _bounding_box_dimensions(largest)
    thickness = min(dims)

    return thickness
