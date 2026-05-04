from dataclasses import dataclass, field
from typing import Optional, Any
from pathlib import Path
import cadquery as cq

@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0

    @property
    def hex(self) -> str:
        """Return hex representation #RRGGBB."""
        return f"#{int(self.r*255):02x}{int(self.g*255):02x}{int(self.b*255):02x}"

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)


@dataclass
class Part:
    name: str
    width_mm: float
    height_mm: float
    area_mm2: float
    count: int
    color: Optional[Color]


@dataclass
class PlacedPart:
    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotated: bool = False
    part_id: Optional[int] = None


@dataclass
class SheetConfig:
    color: str
    name: str
    width_mm: float
    height_mm: float


@dataclass
class SheetResult:
    config: SheetConfig
    index: int
    label: str
    placed_parts: list[PlacedPart]
    total_parts_area_mm2: float = 0.0


@dataclass
class PartConfig:
    flip_horizontal: bool = False
    flip_vertical: bool = False


@dataclass
class FileImport:
    file: str
    parts: dict[str, PartConfig] = field(default_factory=dict)


@dataclass
class PlacementConfig:
    sheet_margin_mm: float = 10.0
    part_margin_mm: float = 5.0
    label_square_size_mm: float = 15.0
    part_label_size_mm: float = 3.2


@dataclass
class ProjectConfig:
    imports: list[FileImport] = field(default_factory=list)
    overlays: dict[str, Any] = field(default_factory=dict)
    sheets: list[SheetConfig] = field(default_factory=list)
    placement: PlacementConfig = field(default_factory=PlacementConfig())
