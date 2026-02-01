"""Main trace router using A* pathfinding."""
from typing import Optional

from backend.pcb.parser import PCBParser

from .obstacles import ObstacleMap, ElementAwareMap
from .pathfinding import astar_search, astar_search_element_aware
from .pending import PendingTraceStore


class TraceRouter:
    """
    Router for creating traces between points on a PCB.

    Uses A* pathfinding with 8-direction movement (0°, 45°, 90°, etc.)
    to find paths that avoid obstacles while respecting clearances.
    """

    # Copper layers to cache
    COPPER_LAYERS = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

    def __init__(
        self,
        parser: PCBParser,
        clearance: float = 0.2,
        grid_resolution: float = 0.025,
        cache_obstacles: bool = False,
        use_element_aware: bool = True
    ):
        """
        Initialize the router.

        Args:
            parser: Parsed PCB data
            clearance: Minimum clearance to obstacles (mm)
            grid_resolution: Routing grid cell size (mm)
            cache_obstacles: Whether to cache obstacle maps at startup
            use_element_aware: Use element-aware pathfinding with exact geometry
        """
        self.parser = parser
        self.clearance = clearance
        self.grid_resolution = grid_resolution
        self.use_element_aware = use_element_aware

        # Cache obstacle maps per layer (legacy)
        self._obstacle_cache: dict[str, ObstacleMap] = {}

        # Cache element-aware maps per layer (new)
        self._element_aware_cache: dict[str, ElementAwareMap] = {}

        # Store for pending user-created traces
        self.pending_store = PendingTraceStore(grid_resolution=grid_resolution)

        if cache_obstacles:
            if use_element_aware:
                self._build_element_aware_cache()
            else:
                self._build_obstacle_cache()

    def _build_obstacle_cache(self) -> None:
        """Pre-build obstacle maps for all copper layers."""
        for layer in self.COPPER_LAYERS:
            self._obstacle_cache[layer] = ObstacleMap(
                parser=self.parser,
                layer=layer,
                clearance=self.clearance,
                grid_resolution=self.grid_resolution,
                allowed_net_id=None  # Block everything
            )

    def _build_element_aware_cache(self) -> None:
        """Pre-build element-aware maps for all copper layers."""
        for layer in self.COPPER_LAYERS:
            self._element_aware_cache[layer] = ElementAwareMap(
                parser=self.parser,
                layer=layer,
                clearance=self.clearance,
                grid_resolution=self.grid_resolution
            )

    def _get_obstacle_map(self, layer: str, net_id: Optional[int]) -> ObstacleMap:
        """Get obstacle map, using cache if available."""
        if layer in self._obstacle_cache and net_id is None:
            return self._obstacle_cache[layer]

        # Need to build a new one (with net filtering or uncached layer)
        return ObstacleMap(
            parser=self.parser,
            layer=layer,
            clearance=self.clearance,
            grid_resolution=self.grid_resolution,
            allowed_net_id=net_id
        )

    def route(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        layer: str,
        width: float,
        net_id: Optional[int] = None
    ) -> list[tuple[float, float]]:
        """
        Route a trace between two points.

        Args:
            start_x, start_y: Start position (mm)
            end_x, end_y: End position (mm)
            layer: Copper layer (e.g., 'F.Cu', 'B.Cu')
            width: Trace width (mm)
            net_id: Optional net ID to allow crossing same-net elements

        Returns:
            List of (x, y) waypoints defining the trace path.
            Returns empty list if no valid route found.
        """
        if self.use_element_aware:
            return self._route_element_aware(
                start_x, start_y, end_x, end_y, layer, width, net_id
            )
        else:
            return self._route_legacy(
                start_x, start_y, end_x, end_y, layer, width, net_id
            )

    def _route_element_aware(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        layer: str,
        width: float,
        net_id: Optional[int] = None
    ) -> list[tuple[float, float]]:
        """Route using element-aware pathfinding with exact geometry."""
        # Get element-aware map
        if layer not in self._element_aware_cache:
            self._element_aware_cache[layer] = ElementAwareMap(
                parser=self.parser,
                layer=layer,
                clearance=self.clearance,
                grid_resolution=self.grid_resolution
            )

        obstacle_map = self._element_aware_cache[layer]

        # Get pending traces for this layer (excluding same-net)
        pending = self.pending_store.get_traces_by_layer(layer)
        pending_filtered = [t for t in pending
                           if net_id is None or t.net_id != net_id]

        return astar_search_element_aware(
            obstacle_map,
            start_x, start_y,
            end_x, end_y,
            trace_radius=width / 2,
            net_id=net_id,
            pending_traces=pending_filtered if pending_filtered else None
        )

    def _route_legacy(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        layer: str,
        width: float,
        net_id: Optional[int] = None
    ) -> list[tuple[float, float]]:
        """Route using legacy grid-based pathfinding."""
        # Get blocked cells from pending traces (excluding same-net traces)
        pending_blocked = self.pending_store.get_blocked_cells(
            layer, self.clearance, exclude_net_id=net_id
        )

        # Get or build obstacle map
        if net_id is not None and layer in self._obstacle_cache:
            # Use cached map but compute allowed cells for this net
            base_map = self._obstacle_cache[layer]
            allowed_cells = self._get_net_cells(layer, net_id)
            path = astar_search(
                base_map,
                start_x, start_y,
                end_x, end_y,
                width / 2,
                allowed_cells=allowed_cells,
                extra_blocked=pending_blocked
            )
        else:
            obstacle_map = self._get_obstacle_map(layer, net_id)
            path = astar_search(
                obstacle_map,
                start_x, start_y,
                end_x, end_y,
                width / 2,
                extra_blocked=pending_blocked
            )

        return path

    def _get_net_cells(self, layer: str, net_id: int) -> set[tuple[int, int]]:
        """Get set of grid cells that belong to a specific net.

        For rotated pads, the allowed region is expanded to match the blocking
        radius so routes can escape. However, cells blocked by different-net
        elements are excluded to prevent clearance violations.
        """
        import math
        resolution = self.grid_resolution
        cells: set[tuple[int, int]] = set()

        def to_grid(x: float, y: float) -> tuple[int, int]:
            return (int(round(x / resolution)), int(round(y / resolution)))

        # Collect cells blocked by DIFFERENT-net pads (to exclude from allowed)
        different_net_blocked: set[tuple[int, int]] = set()
        for pad in self.parser.pads:
            if layer not in pad.layers or pad.net_id == net_id:
                continue  # Skip same-net or different-layer pads

            gx, gy = to_grid(pad.x, pad.y)

            # Calculate blocking radius (must match ObstacleMap._block_rect)
            if pad.angle != 0:
                w = pad.width + 2 * self.clearance
                h = pad.height + 2 * self.clearance
                radius = math.sqrt(w * w + h * h) / 2
            else:
                # For rectangular pads, use the larger dimension as radius
                w = pad.width + 2 * self.clearance
                h = pad.height + 2 * self.clearance
                radius = max(w, h) / 2

            r = int(radius / resolution) + 1
            r_sq = r * r
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= r_sq:
                        different_net_blocked.add((gx + dx, gy + dy))

        # Add pad cells for this net
        for pad in self.parser.pads:
            if layer not in pad.layers or pad.net_id != net_id:
                continue
            gx, gy = to_grid(pad.x, pad.y)

            # For rotated pads, use circle with diagonal radius
            # Strategy: include cells in the expanded region (for escaping),
            # but exclude any that overlap with different-net blocking zones.
            # Always keep a minimal core (just the pad center) for reachability.
            if pad.angle != 0:
                # Always include minimal core (pad center +/- 1 cell)
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        cells.add((gx + dx, gy + dy))

                # Add expanded region, excluding different-net overlap
                w = pad.width + 2 * self.clearance
                h = pad.height + 2 * self.clearance
                radius = math.sqrt(w * w + h * h) / 2
                r = int(radius / resolution) + 1
                r_sq = r * r
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        if dx * dx + dy * dy <= r_sq:
                            cell = (gx + dx, gy + dy)
                            if cell not in different_net_blocked:
                                cells.add(cell)
            else:
                # For non-rotated pads: minimal core + expansion minus overlap
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        cells.add((gx + dx, gy + dy))

                # Add clearance expansion, excluding different-net overlap
                rx = int((pad.width / 2 + self.clearance) / resolution) + 1
                ry = int((pad.height / 2 + self.clearance) / resolution) + 1
                for dx in range(-rx, rx + 1):
                    for dy in range(-ry, ry + 1):
                        cell = (gx + dx, gy + dy)
                        if cell not in different_net_blocked:
                            cells.add(cell)

        # Add trace cells (only within trace geometry, no clearance)
        for trace in self.parser.get_traces_by_layer(layer):
            if trace.net_id != net_id:
                continue
            # Add cells along the trace
            x1, y1 = trace.start_x, trace.start_y
            x2, y2 = trace.end_x, trace.end_y
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length < 0.001:
                gx, gy = to_grid(x1, y1)
                cells.add((gx, gy))
                continue
            steps = int(length / resolution) + 1
            for i in range(steps + 1):
                t = i / steps
                px = x1 + t * (x2 - x1)
                py = y1 + t * (y2 - y1)
                gx, gy = to_grid(px, py)
                # Only cover the actual trace width
                r = int((trace.width / 2) / resolution) + 1
                for ddx in range(-r, r + 1):
                    for ddy in range(-r, r + 1):
                        cells.add((gx + ddx, gy + ddy))

        # Add via cells (only within via geometry, no clearance)
        for via in self.parser.vias:
            if via.net_id != net_id:
                continue
            gx, gy = to_grid(via.x, via.y)
            # Only cover the actual via area
            r = int((via.size / 2) / resolution) + 1
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    cells.add((gx + dx, gy + dy))

        return cells

    def check_via_placement(
        self,
        x: float,
        y: float,
        via_radius: float,
        net_id: Optional[int] = None
    ) -> tuple[bool, str]:
        """
        Check if a via can be placed at the given coordinates.

        Uses cached obstacle maps for efficiency and excludes same-net elements.

        Args:
            x, y: Via position (mm)
            via_radius: Via outer radius (mm)
            net_id: Net ID to allow crossing (same net elements are OK)

        Returns:
            Tuple of (valid, message). If not valid, message explains why.
        """
        for layer in self.COPPER_LAYERS:
            if self.use_element_aware:
                # Use element-aware checking with exact geometry
                if layer not in self._element_aware_cache:
                    self._element_aware_cache[layer] = ElementAwareMap(
                        parser=self.parser,
                        layer=layer,
                        clearance=self.clearance,
                        grid_resolution=self.grid_resolution
                    )
                obstacle_map = self._element_aware_cache[layer]
                if obstacle_map.is_blocked(x, y, via_radius, net_id):
                    return (False, f"Clearance violation on {layer}")
            else:
                # Use cached obstacle map (legacy)
                if layer in self._obstacle_cache:
                    obstacle_map = self._obstacle_cache[layer]
                    if obstacle_map.is_blocked(x, y, via_radius):
                        # Check if blocked ONLY by same-net elements
                        if net_id is not None and self._is_same_net_only(x, y, via_radius, layer, net_id):
                            continue  # Same-net blocking is OK
                        return (False, f"Clearance violation on {layer}")
                else:
                    # Fall back to building map (shouldn't happen with cache_obstacles=True)
                    obstacle_map = self._get_obstacle_map(layer, net_id)
                    if obstacle_map.is_blocked(x, y, via_radius):
                        return (False, f"Clearance violation on {layer}")

        return (True, "")

    def _is_same_net_only(
        self,
        x: float,
        y: float,
        radius: float,
        layer: str,
        net_id: int
    ) -> bool:
        """
        Check if a position is blocked ONLY by elements of the same net.

        Returns True if all blocking elements belong to the specified net.
        """
        check_radius = radius + self.clearance

        # Check pads
        for pad in self.parser.pads:
            if layer not in pad.layers:
                continue
            pad_radius = max(pad.width, pad.height) / 2 + self.clearance
            dist = ((pad.x - x) ** 2 + (pad.y - y) ** 2) ** 0.5
            if dist <= check_radius + pad_radius:
                if pad.net_id != net_id:
                    return False  # Different net element is blocking

        # Check traces
        for trace in self.parser.get_traces_by_layer(layer):
            # Point-to-line-segment distance
            dist = self._point_to_segment_distance(
                x, y,
                trace.start_x, trace.start_y,
                trace.end_x, trace.end_y
            )
            trace_radius = trace.width / 2 + self.clearance
            if dist <= check_radius + trace_radius:
                if trace.net_id != net_id:
                    return False  # Different net element is blocking

        # Check vias (they span all layers)
        for via in self.parser.vias:
            via_check_radius = via.size / 2 + self.clearance
            dist = ((via.x - x) ** 2 + (via.y - y) ** 2) ** 0.5
            if dist <= check_radius + via_check_radius:
                if via.net_id != net_id:
                    return False  # Different net element is blocking

        return True  # Only same-net elements are blocking

    def _point_to_segment_distance(
        self,
        px: float, py: float,
        x1: float, y1: float,
        x2: float, y2: float
    ) -> float:
        """Calculate shortest distance from point to line segment."""
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq < 0.0001:
            return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5

    def find_net_at_point(
        self,
        x: float,
        y: float,
        layer: str,
        tolerance: float = 0.5
    ) -> Optional[int]:
        """
        Find the net ID at a given point (pad or via).

        Returns the net of the CLOSEST pad/via within tolerance.

        Args:
            x, y: Position to check (mm)
            layer: Layer to check
            tolerance: Search radius (mm)

        Returns:
            Net ID if found, None otherwise
        """
        best_net_id: Optional[int] = None
        best_dist = tolerance + 1  # Start with value beyond tolerance

        # Check pads - find closest one
        for pad in self.parser.pads:
            if layer not in pad.layers:
                continue
            dist = ((pad.x - x) ** 2 + (pad.y - y) ** 2) ** 0.5
            if dist <= tolerance and dist < best_dist:
                best_dist = dist
                best_net_id = pad.net_id

        # Check vias - find closest one
        for via in self.parser.vias:
            dist = ((via.x - x) ** 2 + (via.y - y) ** 2) ** 0.5
            if dist <= tolerance and dist < best_dist:
                best_dist = dist
                best_net_id = via.net_id

        return best_net_id
