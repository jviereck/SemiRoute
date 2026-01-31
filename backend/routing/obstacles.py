"""Obstacle map for PCB routing."""
import math
from dataclasses import dataclass
from typing import Optional

from backend.pcb.parser import PCBParser
from backend.pcb.models import PadInfo, TraceInfo, ViaInfo, GraphicLine, GraphicArc


@dataclass
class ObstacleMap:
    """
    Grid-based obstacle map for routing.

    Uses a sparse representation - only stores blocked cells.
    """

    def __init__(
        self,
        parser: PCBParser,
        layer: str,
        clearance: float = 0.2,
        grid_resolution: float = 0.025,
        allowed_net_id: Optional[int] = None
    ):
        """
        Initialize obstacle map from parsed PCB.

        Args:
            parser: Parsed PCB data
            layer: Copper layer to route on
            clearance: Minimum clearance to obstacles (mm)
            grid_resolution: Grid cell size (mm)
            allowed_net_id: Net ID that can be crossed (same net routing)
        """
        self.parser = parser
        self.layer = layer
        self.clearance = clearance
        self.resolution = grid_resolution
        self.allowed_net_id = allowed_net_id

        # Blocked cells: set of (grid_x, grid_y) tuples
        self._blocked: set[tuple[int, int]] = set()

        # Build obstacle map
        self._build_obstacles()

    def _to_grid(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid coordinates."""
        return (
            int(round(x / self.resolution)),
            int(round(y / self.resolution))
        )

    def _to_world(self, gx: int, gy: int) -> tuple[float, float]:
        """Convert grid coordinates to world coordinates."""
        return (gx * self.resolution, gy * self.resolution)

    def _block_circle(self, cx: float, cy: float, radius: float) -> None:
        """Block all grid cells within a circle."""
        # Expand by clearance
        r = radius + self.clearance

        # Grid bounds
        gx, gy = self._to_grid(cx, cy)
        gr = int(math.ceil(r / self.resolution)) + 1

        for dx in range(-gr, gr + 1):
            for dy in range(-gr, gr + 1):
                # Check if cell center is within radius
                wx, wy = self._to_world(gx + dx, gy + dy)
                dist = math.sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
                if dist <= r:
                    self._blocked.add((gx + dx, gy + dy))

    def _block_rect(
        self,
        cx: float, cy: float,
        width: float, height: float,
        angle: float = 0
    ) -> None:
        """Block all grid cells within a rectangle."""
        # Expand by clearance
        w = width + 2 * self.clearance
        h = height + 2 * self.clearance

        # For rotated rectangles, use bounding circle approximation
        if angle != 0:
            # Use diagonal as radius
            radius = math.sqrt(w * w + h * h) / 2
            self._block_circle(cx, cy, radius - self.clearance)
            return

        # Axis-aligned rectangle
        gx1, gy1 = self._to_grid(cx - w / 2, cy - h / 2)
        gx2, gy2 = self._to_grid(cx + w / 2, cy + h / 2)

        for gx in range(gx1, gx2 + 1):
            for gy in range(gy1, gy2 + 1):
                self._blocked.add((gx, gy))

    def _block_line(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        width: float
    ) -> None:
        """Block all grid cells along a line segment with given width."""
        # Expand by clearance
        r = width / 2 + self.clearance

        # Line length and direction
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)

        if length < 0.001:
            self._block_circle(x1, y1, r)
            return

        # Step along line
        steps = int(math.ceil(length / self.resolution)) + 1
        for i in range(steps + 1):
            t = i / steps
            px = x1 + t * dx
            py = y1 + t * dy
            self._block_circle(px, py, r - self.clearance)

    def _build_obstacles(self) -> None:
        """Build obstacle map from PCB elements."""
        # Add pads on this layer
        for pad in self.parser.pads:
            if self.layer not in pad.layers:
                continue
            # Skip pads of allowed net
            if self.allowed_net_id is not None and pad.net_id == self.allowed_net_id:
                continue

            if pad.shape == 'circle':
                radius = min(pad.width, pad.height) / 2
                self._block_circle(pad.x, pad.y, radius)
            elif pad.shape == 'oval':
                # Use larger dimension as circle approximation
                radius = max(pad.width, pad.height) / 2
                self._block_circle(pad.x, pad.y, radius)
            else:  # rect, roundrect
                self._block_rect(pad.x, pad.y, pad.width, pad.height, pad.angle)

        # Add traces on this layer
        for trace in self.parser.get_traces_by_layer(self.layer):
            # Skip traces of allowed net
            if self.allowed_net_id is not None and trace.net_id == self.allowed_net_id:
                continue
            self._block_line(
                trace.start_x, trace.start_y,
                trace.end_x, trace.end_y,
                trace.width
            )

        # Add vias (they span all layers)
        for via in self.parser.vias:
            # Skip vias of allowed net
            if self.allowed_net_id is not None and via.net_id == self.allowed_net_id:
                continue
            radius = via.size / 2
            self._block_circle(via.x, via.y, radius)

        # Add edge cuts (board outline)
        for item in self.parser.edge_cuts:
            if isinstance(item, GraphicLine):
                # Block outside the board edge
                self._block_line(
                    item.start_x, item.start_y,
                    item.end_x, item.end_y,
                    item.width + self.clearance * 2
                )

    def is_blocked(self, x: float, y: float, radius: float = 0) -> bool:
        """
        Check if a position is blocked.

        Args:
            x: World X coordinate
            y: World Y coordinate
            radius: Additional radius to check (for trace width)

        Returns:
            True if position is blocked
        """
        gx, gy = self._to_grid(x, y)

        if radius <= 0:
            return (gx, gy) in self._blocked

        # Check cells within radius
        gr = int(math.ceil(radius / self.resolution)) + 1
        for dx in range(-gr, gr + 1):
            for dy in range(-gr, gr + 1):
                if (gx + dx, gy + dy) in self._blocked:
                    # Check actual distance
                    wx, wy = self._to_world(gx + dx, gy + dy)
                    if math.sqrt((wx - x) ** 2 + (wy - y) ** 2) <= radius:
                        return True
        return False

    def is_grid_blocked(self, gx: int, gy: int) -> bool:
        """Check if a grid cell is blocked."""
        return (gx, gy) in self._blocked

    def get_bounds(self) -> tuple[int, int, int, int]:
        """Get grid bounds (min_gx, min_gy, max_gx, max_gy)."""
        info = self.parser.get_board_info()
        min_gx, min_gy = self._to_grid(info.min_x - 1, info.min_y - 1)
        max_gx, max_gy = self._to_grid(info.max_x + 1, info.max_y + 1)
        return (min_gx, min_gy, max_gx, max_gy)
