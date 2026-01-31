"""Pending trace storage for user-created routes."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PendingTrace:
    """Represents a user-created trace that hasn't been committed to the PCB."""
    id: str
    segments: list[tuple[float, float]]
    width: float
    layer: str
    net_id: Optional[int] = None


class PendingTraceStore:
    """
    Stores pending user traces for clearance checking.

    When routing new traces, these pending traces should be considered
    as obstacles to avoid routing through already-placed user traces.
    """

    def __init__(self, grid_resolution: float = 0.025):
        """
        Initialize the pending trace store.

        Args:
            grid_resolution: Grid cell size for blocked cell calculation (mm)
        """
        self._traces: dict[str, PendingTrace] = {}
        self._grid_resolution = grid_resolution
        # Cache of blocked cells per layer
        self._blocked_cells_cache: dict[str, set[tuple[int, int]]] = {}

    def add_trace(
        self,
        trace_id: str,
        segments: list[tuple[float, float]],
        width: float,
        layer: str,
        net_id: Optional[int] = None
    ) -> None:
        """
        Add a new pending trace.

        Args:
            trace_id: Unique identifier for this trace
            segments: List of (x, y) points defining the trace path
            width: Trace width in mm
            layer: Copper layer (e.g., 'F.Cu')
            net_id: Optional net ID this trace belongs to
        """
        trace = PendingTrace(
            id=trace_id,
            segments=segments,
            width=width,
            layer=layer,
            net_id=net_id
        )
        self._traces[trace_id] = trace
        # Invalidate cache for this layer
        self._blocked_cells_cache.pop(layer, None)

    def remove_trace(self, trace_id: str) -> bool:
        """
        Remove a pending trace.

        Args:
            trace_id: ID of the trace to remove

        Returns:
            True if trace was found and removed, False otherwise
        """
        trace = self._traces.pop(trace_id, None)
        if trace:
            # Invalidate cache for this layer
            self._blocked_cells_cache.pop(trace.layer, None)
            return True
        return False

    def get_trace(self, trace_id: str) -> Optional[PendingTrace]:
        """Get a trace by ID."""
        return self._traces.get(trace_id)

    def get_all_traces(self) -> list[PendingTrace]:
        """Get all pending traces."""
        return list(self._traces.values())

    def get_traces_by_layer(self, layer: str) -> list[PendingTrace]:
        """Get all traces on a specific layer."""
        return [t for t in self._traces.values() if t.layer == layer]

    def clear(self) -> None:
        """Remove all pending traces."""
        self._traces.clear()
        self._blocked_cells_cache.clear()

    def get_blocked_cells(
        self,
        layer: str,
        clearance: float = 0.2,
        exclude_net_id: Optional[int] = None
    ) -> set[tuple[int, int]]:
        """
        Get grid cells blocked by pending traces on a layer.

        Args:
            layer: Copper layer to check
            clearance: Clearance distance in mm
            exclude_net_id: If provided, exclude traces with this net ID

        Returns:
            Set of (grid_x, grid_y) tuples that are blocked
        """
        # Check if we can use cached result (only if no net exclusion)
        if exclude_net_id is None and layer in self._blocked_cells_cache:
            return self._blocked_cells_cache[layer]

        cells: set[tuple[int, int]] = set()
        resolution = self._grid_resolution

        def to_grid(x: float, y: float) -> tuple[int, int]:
            return (int(round(x / resolution)), int(round(y / resolution)))

        for trace in self._traces.values():
            if trace.layer != layer:
                continue
            if exclude_net_id is not None and trace.net_id == exclude_net_id:
                continue

            # Calculate blocked cells along each segment
            segments = trace.segments
            if len(segments) < 2:
                continue

            trace_radius = trace.width / 2 + clearance
            cell_radius = int(trace_radius / resolution) + 1

            for i in range(len(segments) - 1):
                x1, y1 = segments[i]
                x2, y2 = segments[i + 1]

                # Sample points along segment
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 0.001:
                    gx, gy = to_grid(x1, y1)
                    for dx in range(-cell_radius, cell_radius + 1):
                        for dy in range(-cell_radius, cell_radius + 1):
                            cells.add((gx + dx, gy + dy))
                    continue

                steps = max(int(length / resolution), 1)
                for step in range(steps + 1):
                    t = step / steps
                    px = x1 + t * (x2 - x1)
                    py = y1 + t * (y2 - y1)
                    gx, gy = to_grid(px, py)

                    for dx in range(-cell_radius, cell_radius + 1):
                        for dy in range(-cell_radius, cell_radius + 1):
                            cells.add((gx + dx, gy + dy))

        # Cache result if no net exclusion was applied
        if exclude_net_id is None:
            self._blocked_cells_cache[layer] = cells

        return cells

    def is_point_blocked(
        self,
        x: float,
        y: float,
        radius: float,
        layer: str,
        clearance: float = 0.2,
        exclude_net_id: Optional[int] = None
    ) -> bool:
        """
        Check if a point is blocked by any pending trace.

        Args:
            x, y: Point to check (mm)
            radius: Radius around the point to check (mm)
            layer: Layer to check
            clearance: Minimum clearance (mm)
            exclude_net_id: If provided, ignore traces with this net ID

        Returns:
            True if point would violate clearance to any pending trace
        """
        check_radius = radius + clearance

        for trace in self._traces.values():
            if trace.layer != layer:
                continue
            if exclude_net_id is not None and trace.net_id == exclude_net_id:
                continue

            segments = trace.segments
            if len(segments) < 2:
                continue

            trace_radius = trace.width / 2

            # Check distance to each segment
            for i in range(len(segments) - 1):
                dist = self._point_to_segment_distance(
                    x, y,
                    segments[i][0], segments[i][1],
                    segments[i + 1][0], segments[i + 1][1]
                )
                if dist <= check_radius + trace_radius:
                    return True

        return False

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
