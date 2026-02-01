"""Hull management for walkaround routing."""
from __future__ import annotations
import math
from typing import Optional, Iterator
from dataclasses import dataclass

from backend.pcb.parser import PCBParser
from backend.pcb.models import PadInfo, TraceInfo, ViaInfo
from backend.routing.hulls import Point, LineChain, HullGenerator


@dataclass(slots=True)
class IndexedHull:
    """Hull with precomputed bounding box for spatial queries."""
    hull: LineChain
    net_id: int
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    source_type: str  # 'pad', 'trace', 'via'
    source: object  # Original PadInfo, TraceInfo, or ViaInfo


class HullMap:
    """
    Manages hulls for all PCB elements on a layer.

    Uses a grid-based spatial index for fast queries.
    """

    def __init__(
        self,
        parser: PCBParser,
        layer: str,
        clearance: float = 0.2,
        trace_clearance: Optional[float] = None,
        cell_size: float = 2.0
    ):
        """
        Initialize hull map for a layer.

        Args:
            parser: Parsed PCB data
            layer: Copper layer (e.g., 'F.Cu')
            clearance: Default clearance for pads and vias
            trace_clearance: Clearance for traces (defaults to clearance)
            cell_size: Spatial index cell size in mm
        """
        self.parser = parser
        self.layer = layer
        self.clearance = clearance
        self.trace_clearance = trace_clearance if trace_clearance is not None else clearance
        self.cell_size = cell_size
        self._inv_cell_size = 1.0 / cell_size

        # Spatial index: (cell_x, cell_y) -> list of IndexedHull
        self._grid: dict[tuple[int, int], list[IndexedHull]] = {}

        # All hulls (for iteration)
        self._hulls: list[IndexedHull] = []

        # Pending trace hulls (temporary, cleared after each route)
        self._pending_hulls: list[IndexedHull] = []

        # Build hulls
        self._build_hulls()

    def _cell_coords(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid cell coordinates."""
        return (int(math.floor(x * self._inv_cell_size)),
                int(math.floor(y * self._inv_cell_size)))

    def _add_to_grid(self, hull: IndexedHull) -> None:
        """Add hull to spatial index."""
        min_cell = self._cell_coords(hull.min_x, hull.min_y)
        max_cell = self._cell_coords(hull.max_x, hull.max_y)

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                key = (cx, cy)
                if key not in self._grid:
                    self._grid[key] = []
                self._grid[key].append(hull)

    def _build_hulls(self) -> None:
        """Build hulls for all PCB elements on this layer."""
        # Process pads
        for pad in self.parser.pads:
            if self.layer not in pad.layers:
                continue
            hull = self._create_pad_hull(pad)
            if hull:
                self._hulls.append(hull)
                self._add_to_grid(hull)

        # Process traces
        for trace in self.parser.get_traces_by_layer(self.layer):
            hull = self._create_trace_hull(trace)
            if hull:
                self._hulls.append(hull)
                self._add_to_grid(hull)

        # Process vias (span all copper layers)
        for via in self.parser.vias:
            hull = self._create_via_hull(via)
            if hull:
                self._hulls.append(hull)
                self._add_to_grid(hull)

    def _create_pad_hull(self, pad: PadInfo) -> Optional[IndexedHull]:
        """Create hull for a pad."""
        center = Point(pad.x, pad.y)

        # For rotations near 90 or 270 degrees, swap width/height
        # to get the effective dimensions after rotation
        angle_mod = abs(pad.angle) % 180
        swap_dims = 45 < angle_mod < 135

        if swap_dims:
            eff_width = pad.height
            eff_height = pad.width
        else:
            eff_width = pad.width
            eff_height = pad.height

        half_w = eff_width / 2
        half_h = eff_height / 2

        if pad.shape == 'circle':
            chain = HullGenerator.circular_hull(
                center, min(half_w, half_h), self.clearance
            )
        elif pad.shape == 'oval':
            # Oval is a stadium shape - use segment hull
            # Use effective dimensions (accounting for rotation)
            if eff_width > eff_height:
                # Horizontal oval (after accounting for rotation)
                offset = (eff_width - eff_height) / 2
                chain = HullGenerator.segment_hull(
                    Point(center.x - offset, center.y),
                    Point(center.x + offset, center.y),
                    eff_height,
                    self.clearance
                )
            else:
                # Vertical oval (after accounting for rotation)
                offset = (eff_height - eff_width) / 2
                chain = HullGenerator.segment_hull(
                    Point(center.x, center.y - offset),
                    Point(center.x, center.y + offset),
                    eff_width,
                    self.clearance
                )
            # Note: rotation already accounted for in dimension swap,
            # so no need to rotate the chain
        elif pad.angle != 0:
            # Rotated rectangle
            chain = HullGenerator.rotated_rect_hull(
                center, half_w, half_h, pad.angle, self.clearance
            )
        else:
            # Axis-aligned rectangle (or roundrect)
            chain = HullGenerator.octagonal_hull(
                center, half_w, half_h, self.clearance
            )

        chain.net_id = pad.net_id

        # Calculate bounding box
        min_x = min(p.x for p in chain.points)
        max_x = max(p.x for p in chain.points)
        min_y = min(p.y for p in chain.points)
        max_y = max(p.y for p in chain.points)

        return IndexedHull(
            hull=chain,
            net_id=pad.net_id,
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            source_type='pad',
            source=pad
        )

    def _create_trace_hull(self, trace: TraceInfo) -> Optional[IndexedHull]:
        """Create hull for a trace segment."""
        start = Point(trace.start_x, trace.start_y)
        end = Point(trace.end_x, trace.end_y)

        chain = HullGenerator.segment_hull(
            start, end, trace.width, self.trace_clearance
        )
        chain.net_id = trace.net_id

        # Calculate bounding box
        min_x = min(p.x for p in chain.points)
        max_x = max(p.x for p in chain.points)
        min_y = min(p.y for p in chain.points)
        max_y = max(p.y for p in chain.points)

        return IndexedHull(
            hull=chain,
            net_id=trace.net_id,
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            source_type='trace',
            source=trace
        )

    def _create_via_hull(self, via: ViaInfo) -> Optional[IndexedHull]:
        """Create hull for a via."""
        center = Point(via.x, via.y)
        chain = HullGenerator.via_hull(center, via.size, self.clearance)
        chain.net_id = via.net_id

        # Calculate bounding box
        radius = via.size / 2 + self.clearance
        return IndexedHull(
            hull=chain,
            net_id=via.net_id,
            min_x=via.x - radius,
            max_x=via.x + radius,
            min_y=via.y - radius,
            max_y=via.y + radius,
            source_type='via',
            source=via
        )

    def _rotate_chain(self, chain: LineChain, center: Point, angle_deg: float) -> LineChain:
        """Rotate a LineChain around a center point."""
        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_points = []
        for p in chain.points:
            dx = p.x - center.x
            dy = p.y - center.y
            rx = dx * cos_a - dy * sin_a + center.x
            ry = dx * sin_a + dy * cos_a + center.y
            rotated_points.append(Point(rx, ry))

        return LineChain(points=rotated_points, net_id=chain.net_id)

    def query_segment(
        self,
        start: Point,
        end: Point,
        trace_width: float,
        net_id: Optional[int] = None
    ) -> Iterator[IndexedHull]:
        """
        Find all hulls that might intersect with a trace segment.

        Args:
            start, end: Segment endpoints
            trace_width: Width of the trace
            net_id: Net ID to exclude (same-net routing)

        Yields:
            IndexedHull objects that might block the segment
        """
        # Expand bounding box by trace width
        half_width = trace_width / 2
        min_x = min(start.x, end.x) - half_width
        max_x = max(start.x, end.x) + half_width
        min_y = min(start.y, end.y) - half_width
        max_y = max(start.y, end.y) + half_width

        min_cell = self._cell_coords(min_x, min_y)
        max_cell = self._cell_coords(max_x, max_y)

        seen: set[int] = set()

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                hulls = self._grid.get((cx, cy))
                if hulls is None:
                    continue

                for indexed in hulls:
                    hull_id = id(indexed)
                    if hull_id in seen:
                        continue
                    seen.add(hull_id)

                    # Skip same-net hulls
                    if net_id is not None and indexed.net_id == net_id:
                        continue

                    # Bounding box check
                    if (indexed.min_x <= max_x and indexed.max_x >= min_x and
                        indexed.min_y <= max_y and indexed.max_y >= min_y):
                        yield indexed

    def query_point(
        self,
        point: Point,
        radius: float,
        net_id: Optional[int] = None
    ) -> Iterator[IndexedHull]:
        """
        Find all hulls near a point.

        Args:
            point: Query point
            radius: Search radius (should include trace_width/2)
            net_id: Net ID to exclude

        Yields:
            IndexedHull objects near the point
        """
        min_x = point.x - radius
        max_x = point.x + radius
        min_y = point.y - radius
        max_y = point.y + radius

        min_cell = self._cell_coords(min_x, min_y)
        max_cell = self._cell_coords(max_x, max_y)

        seen: set[int] = set()

        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                hulls = self._grid.get((cx, cy))
                if hulls is None:
                    continue

                for indexed in hulls:
                    hull_id = id(indexed)
                    if hull_id in seen:
                        continue
                    seen.add(hull_id)

                    if net_id is not None and indexed.net_id == net_id:
                        continue

                    if (indexed.min_x <= max_x and indexed.max_x >= min_x and
                        indexed.min_y <= max_y and indexed.max_y >= min_y):
                        yield indexed

    def get_blocking_hulls(
        self,
        start: Point,
        end: Point,
        trace_width: float,
        net_id: Optional[int] = None
    ) -> list[tuple[IndexedHull, Point, int]]:
        """
        Get all hulls that actually block a segment, sorted by distance.

        Args:
            start, end: Segment endpoints
            trace_width: Width of the trace being routed
            net_id: Net ID to exclude (same-net routing)

        Returns:
            List of (hull, intersection_point, edge_index) sorted by distance from start
        """
        blocking = []

        for indexed in self.query_segment(start, end, trace_width, net_id):
            intersections = indexed.hull.intersects_segment(start, end)
            if intersections:
                # Use the first (closest) intersection
                pt, edge_idx = intersections[0]
                dist_sq = (pt.x - start.x) ** 2 + (pt.y - start.y) ** 2
                blocking.append((indexed, pt, edge_idx, dist_sq))

        # Sort by distance
        blocking.sort(key=lambda x: x[3])

        # Return without distance
        return [(b[0], b[1], b[2]) for b in blocking]

    def point_inside_any_hull(
        self,
        point: Point,
        net_id: Optional[int] = None
    ) -> Optional[IndexedHull]:
        """
        Check if a point is inside any hull.

        Args:
            point: Point to check
            net_id: Net ID to exclude

        Returns:
            The hull containing the point, or None
        """
        for indexed in self.query_point(point, 0.1, net_id):
            if indexed.hull.point_inside(point):
                return indexed
        return None

    def all_hulls(self) -> list[IndexedHull]:
        """Get all hulls in the map."""
        return self._hulls

    def add_pending_trace(
        self,
        trace_id: str,
        segments: list[tuple[float, float]],
        width: float,
        net_id: Optional[int] = None
    ) -> None:
        """
        Add a pending trace as temporary hulls.

        These hulls will be considered for collision checking until
        clear_pending_hulls() is called.

        Args:
            trace_id: Unique identifier for the trace
            segments: List of (x, y) waypoints
            width: Trace width in mm
            net_id: Net ID of the trace (same-net crossings allowed)
        """
        if len(segments) < 2:
            return  # No segments to add

        # Create a hull for each segment
        for i in range(len(segments) - 1):
            start = Point(segments[i][0], segments[i][1])
            end = Point(segments[i + 1][0], segments[i + 1][1])

            chain = HullGenerator.segment_hull(
                start, end, width, self.trace_clearance
            )
            chain.net_id = net_id

            # Calculate bounding box
            min_x = min(p.x for p in chain.points)
            max_x = max(p.x for p in chain.points)
            min_y = min(p.y for p in chain.points)
            max_y = max(p.y for p in chain.points)

            indexed = IndexedHull(
                hull=chain,
                net_id=net_id if net_id else 0,
                min_x=min_x,
                max_x=max_x,
                min_y=min_y,
                max_y=max_y,
                source_type='pending',
                source={'trace_id': trace_id, 'segment': i}
            )

            self._pending_hulls.append(indexed)
            self._hulls.append(indexed)
            self._add_to_grid(indexed)

    def clear_pending_hulls(self) -> None:
        """Remove all pending trace hulls."""
        if not self._pending_hulls:
            return  # Nothing to clear

        # Remove from _hulls list
        pending_set = set(id(h) for h in self._pending_hulls)
        self._hulls = [h for h in self._hulls if id(h) not in pending_set]

        # Remove from grid - rebuild the affected cells
        # For simplicity, rebuild the entire grid
        self._grid.clear()
        for hull in self._hulls:
            self._add_to_grid(hull)

        self._pending_hulls.clear()
