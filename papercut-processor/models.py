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
    base_name: Optional[str] = None # Original CAD name before disambiguation
    extra_count: int = 0  # Additional spare copies for sheet placement


_IDENTITY_MATRIX = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


@dataclass
class PartInstance:
    name: str
    color: Optional[Color]
    solid: cq.Shape
    matrix: list[float] # 4x4 transformation matrix
    group_id: Optional[int] = None
    sheet_label: Optional[str] = None
    sheet_part_id: Optional[int] = None
    # Column-major 4x4 rotation mapping the group's canonical geometry onto this
    # instance's own orientation. Identity for the canonical instance; non-trivial
    # when the STEP baked different orientations into congruent (deduplicated)
    # parts. Composed with `matrix` at export time.
    align_matrix: list[float] = field(default_factory=lambda: list(_IDENTITY_MATRIX))


@dataclass
class EngravingInfo:
    """Resolved engraving for a part group."""
    side: str                                  # "top" or "bottom" — the resolved face (after flip_side)
    svg: str = ""                              # SVG path data of the aligned engraving (2D DXF coords)
    transform: Optional[list[float]] = None    # column-major 4x4 mapping 2D DXF -> local 3D
    auto_side: Optional[str] = None            # auto-detected face before any flip_side override
    flip_horizontal: bool = False              # overlay flip_horizontal used to generate the svg
    flip_vertical: bool = False                # overlay flip_vertical used to generate the svg


@dataclass
class PartGroup:
    """A group of identical parts (same geometry and color)."""
    id: int
    canonical: cq.Shape
    names: set[str] = field(default_factory=set)
    color: Optional[Color] = None
    count: int = 0
    engraving: Optional[EngravingInfo] = None


@dataclass
class PlacedPart:
    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotated: bool = False
    part_id: Optional[int] = None
    base_name: Optional[str] = None
    is_spare: bool = False


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
    """Per-part cut configuration (the `cut_overrides` section).

    The flips mirror the 2D cut profile so paired directional parts are engraved
    on the correct physical face; they do not affect the 3D model.
    """
    flip_horizontal: bool = False
    flip_vertical: bool = False


@dataclass
class EngravingOverride:
    """Per-part engraving configuration (the `engraving_overrides` section)."""
    # Overlay-alignment flips (mirror the engraving overlay before matching it to
    # the cut profile).
    flip_horizontal: bool = False
    flip_vertical: bool = False
    # Flip the auto-detected engraving side (top <-> bottom) for the whole part.
    flip_side: bool = False
    # Instance ordinals (the `#N` in the manual instance id) whose side is flipped
    # relative to the part's resolved side.
    flip_side_instances: set[int] = field(default_factory=set)


@dataclass
class PartOptions:
    """Per-part options (the `part_options` section)."""
    extra_count: int = 0
    inner_hole_bridges: bool = False


@dataclass
class FileImport:
    file: str


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
    cut_overrides: dict[str, PartConfig] = field(default_factory=dict)
    engraving_overrides: dict[str, EngravingOverride] = field(default_factory=dict)
    part_options: dict[str, PartOptions] = field(default_factory=dict)
    sheets: list[SheetConfig] = field(default_factory=list)
    placement: PlacementConfig = field(default_factory=PlacementConfig)
    bridges: BridgeConfig = field(default_factory=BridgeConfig)
    kerf: KerfConfig = field(default_factory=KerfConfig)
