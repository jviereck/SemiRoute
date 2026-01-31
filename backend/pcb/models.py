"""Data models for PCB elements."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PadInfo:
    """Information about a single pad."""
    name: str  # Pad number/name (e.g., "1", "2", "A1")
    x: float  # Absolute X position (mm)
    y: float  # Absolute Y position (mm)
    width: float  # Pad width (mm)
    height: float  # Pad height (mm)
    shape: str  # circle, rect, roundrect, oval
    angle: float  # Rotation angle (degrees)
    layers: list[str]  # Copper layers this pad is on
    net_id: int  # Net number
    net_name: str  # Net name
    footprint_ref: str  # Parent footprint reference (e.g., "U1")
    roundrect_ratio: float = 0.0  # Corner radius ratio for roundrect
    drill: Optional[float] = None  # Drill diameter for through-hole pads

    @property
    def pad_id(self) -> str:
        """Unique pad identifier: footprint_ref + pad name."""
        return f"{self.footprint_ref}_{self.name}"


@dataclass
class FootprintInfo:
    """Information about a footprint."""
    reference: str  # Reference designator (e.g., "U1", "R1")
    value: str  # Component value
    x: float  # Position X
    y: float  # Position Y
    angle: float  # Rotation angle (degrees)
    layer: str  # Layer (F.Cu or B.Cu)
    pads: list[PadInfo] = field(default_factory=list)


@dataclass
class GraphicLine:
    """A line graphic element."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float
    layer: str


@dataclass
class GraphicArc:
    """An arc graphic element."""
    start_x: float
    start_y: float
    mid_x: float
    mid_y: float
    end_x: float
    end_y: float
    width: float
    layer: str


@dataclass
class GraphicRect:
    """A rectangle graphic element."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float  # Stroke width
    layer: str
    fill: bool = False


@dataclass
class GraphicCircle:
    """A circle graphic element."""
    center_x: float
    center_y: float
    radius: float
    width: float  # Stroke width
    layer: str
    fill: bool = False


@dataclass
class GraphicPoly:
    """A polygon graphic element."""
    points: list[tuple[float, float]]
    width: float
    layer: str
    fill: bool = False


@dataclass
class TraceInfo:
    """A copper trace segment."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float
    layer: str
    net_id: int
    net_name: str = ""


@dataclass
class ViaInfo:
    """A via connecting copper layers."""
    x: float
    y: float
    size: float  # Outer diameter
    drill: float  # Drill hole diameter
    layers: list[str]  # Connected layers
    net_id: int
    net_name: str = ""


@dataclass
class BoardInfo:
    """Overall board information."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    layers: list[str]
    footprint_count: int
    pad_count: int
    net_count: int
    trace_count: int = 0
    via_count: int = 0

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y
