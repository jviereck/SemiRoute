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

        # Cache for expanded blocked cells by radius (in grid units)
        self._expanded_cache: dict[int, set[tuple[int, int]]] = {}

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
        r_sq = r * r  # Use squared distance to avoid sqrt

        # Grid center and radius
        gx, gy = self._to_grid(cx, cy)
        gr = int(math.ceil(r / self.resolution)) + 1

        # Offset from grid center to actual center (for accurate distance calc)
        gcx, gcy = self._to_world(gx, gy)
        off_x = cx - gcx
        off_y = cy - gcy
        res = self.resolution

        for dx in range(-gr, gr + 1):
            for dy in range(-gr, gr + 1):
                # Distance from cell center to circle center (squared)
                dist_x = dx * res - off_x
                dist_y = dy * res - off_y
                if dist_x * dist_x + dist_y * dist_y <= r_sq:
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
        r_sq = r * r

        # Line vector
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq < 0.000001:
            self._block_circle(x1, y1, r - self.clearance)
            return

        length = math.sqrt(length_sq)

        # Compute bounding box of the capsule shape
        min_x = min(x1, x2) - r
        max_x = max(x1, x2) + r
        min_y = min(y1, y2) - r
        max_y = max(y1, y2) + r

        # Convert to grid bounds
        gx1, gy1 = self._to_grid(min_x, min_y)
        gx2, gy2 = self._to_grid(max_x, max_y)

        res = self.resolution

        # Check each cell in bounding box
        for gx in range(gx1, gx2 + 1):
            for gy in range(gy1, gy2 + 1):
                # Cell center in world coordinates
                px = gx * res
                py = gy * res

                # Vector from line start to point
                apx = px - x1
                apy = py - y1

                # Project point onto line: t = (AP · AB) / |AB|²
                t = (apx * dx + apy * dy) / length_sq

                # Clamp t to [0, 1] to stay on segment
                if t < 0:
                    t = 0
                elif t > 1:
                    t = 1

                # Closest point on segment
                closest_x = x1 + t * dx
                closest_y = y1 + t * dy

                # Distance squared from cell to closest point
                dist_x = px - closest_x
                dist_y = py - closest_y
                dist_sq = dist_x * dist_x + dist_y * dist_y

                if dist_sq <= r_sq:
                    self._blocked.add((gx, gy))

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

        # Check cells within radius (using squared distance)
        radius_sq = radius * radius
        gr = int(math.ceil(radius / self.resolution)) + 1
        res = self.resolution

        # Offset from grid center to query point
        gcx, gcy = self._to_world(gx, gy)
        off_x = x - gcx
        off_y = y - gcy

        for dx in range(-gr, gr + 1):
            for dy in range(-gr, gr + 1):
                if (gx + dx, gy + dy) in self._blocked:
                    # Check actual distance (squared)
                    dist_x = dx * res - off_x
                    dist_y = dy * res - off_y
                    if dist_x * dist_x + dist_y * dist_y <= radius_sq:
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

    def get_expanded_blocked(self, radius: float) -> set[tuple[int, int]]:
        """
        Get blocked cells expanded by a radius, with caching.

        Args:
            radius: Expansion radius in world units (mm)

        Returns:
            Set of blocked cells expanded by the given radius
        """
        if radius <= 0:
            return self._blocked

        # Convert to grid units and round to avoid floating point issues
        grid_radius = int(round(radius / self.resolution * 100))  # Use centiunits for key

        if grid_radius in self._expanded_cache:
            return self._expanded_cache[grid_radius]

        # Build expanded set
        actual_grid_radius = int(math.ceil(radius / self.resolution))
        radius_sq = actual_grid_radius * actual_grid_radius

        expanded: set[tuple[int, int]] = set()
        for gx, gy in self._blocked:
            for dx in range(-actual_grid_radius, actual_grid_radius + 1):
                for dy in range(-actual_grid_radius, actual_grid_radius + 1):
                    if dx * dx + dy * dy <= radius_sq:
                        expanded.add((gx + dx, gy + dy))

        self._expanded_cache[grid_radius] = expanded
        return expanded
