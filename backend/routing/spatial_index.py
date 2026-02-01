"""Spatial index for fast element lookups."""
import math
from typing import Union, Iterator
from dataclasses import dataclass

from backend.pcb.models import PadInfo, TraceInfo, ViaInfo

Element = Union[PadInfo, TraceInfo, ViaInfo]

# All copper layers that vias can span
COPPER_LAYERS = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]


@dataclass
class IndexedElement:
    """Element with precomputed bounding info for spatial queries."""
    element: Element
    min_x: float
    max_x: float
    min_y: float
    max_y: float


class SpatialIndex:
    """
    Grid-based spatial index for fast nearby element queries.

    Uses a coarse grid (e.g., 1mm cells) to bucket elements by location.
    For a query point, only checks elements in nearby grid cells.
    """

    def __init__(self, cell_size: float = 1.0, clearance: float = 0.2):
        """
        Initialize spatial index.

        Args:
            cell_size: Size of grid cells in mm (larger = faster build, slower query)
            clearance: Design rule clearance in mm (used to expand bounding boxes)
        """
        self.cell_size = cell_size
        self.clearance = clearance

        # Grid: dict mapping (cell_x, cell_y) -> list of IndexedElements
        self._grid: dict[tuple[int, int], list[IndexedElement]] = {}

        # All elements by layer for layer-specific queries
        self._elements_by_layer: dict[str, list[IndexedElement]] = {}

    def _cell_coords(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid cell coordinates."""
        return (int(math.floor(x / self.cell_size)),
                int(math.floor(y / self.cell_size)))

    def add_pad(self, pad: PadInfo) -> None:
        """Add a pad to the index."""
        # Calculate bounding box accounting for rotation
        if pad.angle != 0:
            # For rotated pad, use diagonal as bounding radius
            diag = math.sqrt(pad.width ** 2 + pad.height ** 2) / 2
            extent = diag + self.clearance
        else:
            extent = max(pad.width, pad.height) / 2 + self.clearance

        indexed = IndexedElement(
            element=pad,
            min_x=pad.x - extent,
            max_x=pad.x + extent,
            min_y=pad.y - extent,
            max_y=pad.y + extent
        )

        self._add_to_grid(indexed)
        for layer in pad.layers:
            self._add_to_layer(layer, indexed)

    def add_trace(self, trace: TraceInfo) -> None:
        """Add a trace to the index."""
        extent = trace.width / 2 + self.clearance

        indexed = IndexedElement(
            element=trace,
            min_x=min(trace.start_x, trace.end_x) - extent,
            max_x=max(trace.start_x, trace.end_x) + extent,
            min_y=min(trace.start_y, trace.end_y) - extent,
            max_y=max(trace.start_y, trace.end_y) + extent
        )

        self._add_to_grid(indexed)
        self._add_to_layer(trace.layer, indexed)

    def add_via(self, via: ViaInfo) -> None:
        """Add a via to the index (spans all copper layers)."""
        extent = via.size / 2 + self.clearance

        indexed = IndexedElement(
            element=via,
            min_x=via.x - extent,
            max_x=via.x + extent,
            min_y=via.y - extent,
            max_y=via.y + extent
        )

        self._add_to_grid(indexed)
        # Vias span all copper layers
        for layer in COPPER_LAYERS:
            self._add_to_layer(layer, indexed)

    def _add_to_grid(self, indexed: IndexedElement) -> None:
        """Add element to all grid cells it overlaps."""
        min_cell = self._cell_coords(indexed.min_x, indexed.min_y)
        max_cell = self._cell_coords(indexed.max_x, indexed.max_y)

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                cell_key = (cx, cy)
                if cell_key not in self._grid:
                    self._grid[cell_key] = []
                self._grid[cell_key].append(indexed)

    def _add_to_layer(self, layer: str, indexed: IndexedElement) -> None:
        """Add element to layer's element list."""
        if layer not in self._elements_by_layer:
            self._elements_by_layer[layer] = []
        self._elements_by_layer[layer].append(indexed)

    def query_nearby(self, x: float, y: float, radius: float,
                     layer: str) -> Iterator[Element]:
        """
        Find all elements that might be within radius of point (x, y).

        This is a coarse filter - caller should use GeometryChecker for exact distance.

        Args:
            x, y: Query point in world coordinates
            radius: Search radius (should include trace_radius + clearance)
            layer: Copper layer to search

        Yields:
            Elements that might be within radius
        """
        # Expand search to cover the query radius
        search_radius = radius + self.cell_size  # Extra cell to be safe

        min_cell = self._cell_coords(x - search_radius, y - search_radius)
        max_cell = self._cell_coords(x + search_radius, y + search_radius)

        seen: set[int] = set()  # Track element IDs to avoid duplicates

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                cell_key = (cx, cy)
                if cell_key not in self._grid:
                    continue

                for indexed in self._grid[cell_key]:
                    elem_id = id(indexed.element)
                    if elem_id in seen:
                        continue

                    # Check if element is on requested layer
                    elem = indexed.element
                    if isinstance(elem, PadInfo):
                        if layer not in elem.layers:
                            continue
                    elif isinstance(elem, TraceInfo):
                        if elem.layer != layer:
                            continue
                    # Vias are already added to all layers, no filter needed

                    # Quick bounding box check
                    if (indexed.min_x <= x + radius and
                        indexed.max_x >= x - radius and
                        indexed.min_y <= y + radius and
                        indexed.max_y >= y - radius):
                        seen.add(elem_id)
                        yield elem

    def get_elements_on_layer(self, layer: str) -> list[IndexedElement]:
        """Get all indexed elements on a layer."""
        return self._elements_by_layer.get(layer, [])
