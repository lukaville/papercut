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
    group_id: Optional[int] = None # Link to deduplication group


@dataclass
class PartInstance:
    name: str
    color: Optional[Color]
    solid: cq.Shape
    matrix: list[float] # 4x4 transformation matrix
    group_id: Optional[int] = None
    sheet_label: Optional[str] = None
    sheet_part_id: Optional[int] = None


@dataclass
class PartGroup:
    """A group of identical parts (same geometry and color)."""
    id: int
    canonical: cq.Shape
    names: set[str] = field(default_factory=set)
    color: Optional[Color] = None
    count: int = 0


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
class BridgeConfig:
    """Configuration for laser-cutting bridges (tabs)."""
    enable: bool = False
    size_mm: float = 0.5
    min_size_all_corners_mm: float = 20.0
    min_length_extra_bridge_mm: float = 100.0
    overcut: bool = False
    overcut_length_mm: float = 2.0


@dataclass
class PlacementConfig:
    sheet_margin_mm: float = 10.0
    part_margin_mm: float = 5.0
    label_square_size_mm: float = 15.0
    part_label_size_mm: float = 3.2


@dataclass
class KerfConfig:
    """Configuration for kerf compensation."""
    compensation: bool = False
    offset_mm: float = 0.0


@dataclass
class ProjectConfig:
    imports: list[FileImport] = field(default_factory=list)
    overlays: dict[str, PartConfig] = field(default_factory=dict)
    sheets: list[SheetConfig] = field(default_factory=list)
    placement: PlacementConfig = field(default_factory=PlacementConfig)
    bridges: BridgeConfig = field(default_factory=BridgeConfig)
    kerf: KerfConfig = field(default_factory=KerfConfig)
