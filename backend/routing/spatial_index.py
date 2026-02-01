"""Spatial index for fast element lookups."""
import math
from typing import Iterator
from dataclasses import dataclass

from backend.pcb.models import PadInfo, TraceInfo, ViaInfo

# Element type constants (avoid isinstance)
ELEM_PAD = 0
ELEM_TRACE = 1
ELEM_VIA = 2

# All copper layers that vias can span
COPPER_LAYERS = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]


@dataclass(slots=True)
class IndexedElement:
    """Element with precomputed info for fast spatial queries."""
    element: object  # PadInfo, TraceInfo, or ViaInfo
    elem_type: int   # ELEM_PAD, ELEM_TRACE, or ELEM_VIA
    net_id: int      # Pre-extracted net ID
    min_x: float
    max_x: float
    min_y: float
    max_y: float


class SpatialIndex:
    """
    Grid-based spatial index for fast nearby element queries.

    Uses a per-layer grid for O(1) layer filtering.
    """

    def __init__(self, cell_size: float = 1.0, clearance: float = 0.2):
        """
        Initialize spatial index.

        Args:
            cell_size: Size of grid cells in mm
            clearance: Design rule clearance in mm (used to expand bounding boxes)
        """
        self.cell_size = cell_size
        self.clearance = clearance
        self._inv_cell_size = 1.0 / cell_size  # Pre-compute for faster division

        # Per-layer grids: layer -> (cell_x, cell_y) -> list of IndexedElements
        self._layer_grids: dict[str, dict[tuple[int, int], list[IndexedElement]]] = {}

    def _cell_coords(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid cell coordinates."""
        return (int(x * self._inv_cell_size) if x >= 0 else int(x * self._inv_cell_size) - 1,
                int(y * self._inv_cell_size) if y >= 0 else int(y * self._inv_cell_size) - 1)

    def _get_layer_grid(self, layer: str) -> dict[tuple[int, int], list[IndexedElement]]:
        """Get or create grid for a layer."""
        if layer not in self._layer_grids:
            self._layer_grids[layer] = {}
        return self._layer_grids[layer]

    def add_pad(self, pad: PadInfo) -> None:
        """Add a pad to the index."""
        # Calculate bounding box accounting for rotation
        if pad.angle != 0:
            diag = math.sqrt(pad.width ** 2 + pad.height ** 2) / 2
            extent = diag + self.clearance
        else:
            extent = max(pad.width, pad.height) / 2 + self.clearance

        indexed = IndexedElement(
            element=pad,
            elem_type=ELEM_PAD,
            net_id=pad.net_id,
            min_x=pad.x - extent,
            max_x=pad.x + extent,
            min_y=pad.y - extent,
            max_y=pad.y + extent
        )

        # Add to each layer the pad is on
        for layer in pad.layers:
            self._add_to_layer_grid(layer, indexed)

    def add_trace(self, trace: TraceInfo) -> None:
        """Add a trace to the index."""
        extent = trace.width / 2 + self.clearance

        indexed = IndexedElement(
            element=trace,
            elem_type=ELEM_TRACE,
            net_id=trace.net_id,
            min_x=min(trace.start_x, trace.end_x) - extent,
            max_x=max(trace.start_x, trace.end_x) + extent,
            min_y=min(trace.start_y, trace.end_y) - extent,
            max_y=max(trace.start_y, trace.end_y) + extent
        )

        self._add_to_layer_grid(trace.layer, indexed)

    def add_via(self, via: ViaInfo) -> None:
        """Add a via to the index (spans all copper layers)."""
        extent = via.size / 2 + self.clearance

        indexed = IndexedElement(
            element=via,
            elem_type=ELEM_VIA,
            net_id=via.net_id,
            min_x=via.x - extent,
            max_x=via.x + extent,
            min_y=via.y - extent,
            max_y=via.y + extent
        )

        # Vias span all copper layers
        for layer in COPPER_LAYERS:
            self._add_to_layer_grid(layer, indexed)

    def _add_to_layer_grid(self, layer: str, indexed: IndexedElement) -> None:
        """Add element to the layer's grid cells."""
        grid = self._get_layer_grid(layer)
        min_cell = self._cell_coords(indexed.min_x, indexed.min_y)
        max_cell = self._cell_coords(indexed.max_x, indexed.max_y)

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                cell_key = (cx, cy)
                if cell_key not in grid:
                    grid[cell_key] = []
                grid[cell_key].append(indexed)

    def query_nearby(self, x: float, y: float, radius: float,
                     layer: str) -> Iterator[IndexedElement]:
        """
        Find all elements that might be within radius of point (x, y).

        Args:
            x, y: Query point in world coordinates
            radius: Search radius (should include trace_radius + clearance)
            layer: Copper layer to search

        Yields:
            IndexedElement objects (caller can access .element, .net_id, .elem_type)
        """
        grid = self._layer_grids.get(layer)
        if grid is None:
            return

        # Expand search to cover the query radius
        search_radius = radius + self.cell_size

        min_cx = int((x - search_radius) * self._inv_cell_size)
        max_cx = int((x + search_radius) * self._inv_cell_size)
        min_cy = int((y - search_radius) * self._inv_cell_size)
        max_cy = int((y + search_radius) * self._inv_cell_size)

        if x - search_radius < 0:
            min_cx -= 1
        if y - search_radius < 0:
            min_cy -= 1

        # Use a set for deduplication by object identity
        seen: set[int] = set()
        x_plus_r = x + radius
        x_minus_r = x - radius
        y_plus_r = y + radius
        y_minus_r = y - radius

        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cell_elements = grid.get((cx, cy))
                if cell_elements is None:
                    continue

                for indexed in cell_elements:
                    elem_id = id(indexed)
                    if elem_id in seen:
                        continue

                    # Quick bounding box check
                    if (indexed.min_x <= x_plus_r and
                        indexed.max_x >= x_minus_r and
                        indexed.min_y <= y_plus_r and
                        indexed.max_y >= y_minus_r):
                        seen.add(elem_id)
                        yield indexed

    def query_cell(self, x: float, y: float, layer: str) -> list[IndexedElement] | None:
        """Get all elements in the cell containing point (x, y)."""
        grid = self._layer_grids.get(layer)
        if grid is None:
            return None
        cell = self._cell_coords(x, y)
        return grid.get(cell)
