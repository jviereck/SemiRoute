"""Walkaround routing algorithm for PCB trace routing."""
from __future__ import annotations
import math
from typing import Optional
from dataclasses import dataclass

from backend.routing.hulls import (
    Point, LineChain, segment_segment_intersection,
    closest_point_on_segment, point_to_segment_distance
)
from backend.routing.hull_map import HullMap, IndexedHull


@dataclass
class WalkaroundResult:
    """Result of a walkaround operation."""
    path: list[Point]
    success: bool
    iterations: int


class WalkaroundRouter:
    """
    Hull-based walkaround router for PCB traces.

    Uses the walkaround algorithm:
    1. Try direct line to goal
    2. If blocked, find first intersecting hull
    3. Walk around hull boundary (try CW and CCW)
    4. Pick shorter valid path
    5. Repeat from exit point until goal reached
    """

    def __init__(
        self,
        hull_map: HullMap,
        trace_width: float,
        max_iterations: int = 1000,
        corner_offset: float = 0.1
    ):
        """
        Initialize walkaround router.

        Args:
            hull_map: Map of hulls for obstacle detection
            trace_width: Width of trace being routed
            max_iterations: Maximum iterations before giving up
            corner_offset: Offset from hull corners (prevents touching)
        """
        self.hull_map = hull_map
        self.trace_width = trace_width
        self.half_width = trace_width / 2
        self.max_iterations = max_iterations
        self.corner_offset = corner_offset

    def route(
        self,
        start: Point,
        end: Point,
        net_id: Optional[int] = None
    ) -> WalkaroundResult:
        """
        Route a trace from start to end using walkaround algorithm.

        Args:
            start: Start point
            end: End point (goal)
            net_id: Net ID for same-net routing (allows crossing same-net)

        Returns:
            WalkaroundResult with path and success status
        """
        path = [start]
        current = start
        iterations = 0
        visited_hulls: set[int] = set()  # Prevent infinite loops

        while iterations < self.max_iterations:
            iterations += 1

            # Check if we can go directly to goal
            blocking = self._find_first_blocking_hull(current, end, net_id)

            if blocking is None:
                # Direct path is clear
                path.append(end)
                return WalkaroundResult(path=path, success=True, iterations=iterations)

            hull, entry_point, entry_edge = blocking

            # Check for infinite loop
            hull_id = id(hull)
            if hull_id in visited_hulls:
                # We've already walked around this hull - try to escape
                # Move slightly away from hull center and retry
                escape = self._try_escape(current, hull, end)
                if escape is not None:
                    path.append(escape)
                    current = escape
                    continue
                else:
                    # Can't escape, fail
                    return WalkaroundResult(path=path, success=False, iterations=iterations)

            visited_hulls.add(hull_id)

            # Walk around the hull in both directions
            cw_path = self._walk_hull(hull.hull, entry_point, entry_edge, end, clockwise=True, net_id=net_id)
            ccw_path = self._walk_hull(hull.hull, entry_point, entry_edge, end, clockwise=False, net_id=net_id)

            # Pick the shorter valid path
            best_path = self._choose_best_path(cw_path, ccw_path, end)

            if best_path is None or len(best_path) == 0:
                # Neither direction worked
                return WalkaroundResult(path=path, success=False, iterations=iterations)

            # Add the walkaround path (excluding entry point which is close to current)
            path.extend(best_path)
            current = best_path[-1]

            # Clear visited hulls when we successfully navigate around one
            # This allows revisiting if we approach from a different angle
            visited_hulls.clear()

        # Max iterations reached
        return WalkaroundResult(path=path, success=False, iterations=iterations)

    def _find_first_blocking_hull(
        self,
        start: Point,
        end: Point,
        net_id: Optional[int]
    ) -> Optional[tuple[IndexedHull, Point, int]]:
        """
        Find the first hull blocking the path from start to end.

        Returns:
            (hull, intersection_point, edge_index) or None if path is clear
        """
        blocking = self.hull_map.get_blocking_hulls(start, end, self.trace_width, net_id)

        if not blocking:
            return None

        # Return the first (closest) blocking hull
        return blocking[0]

    def _walk_hull(
        self,
        hull: LineChain,
        entry_point: Point,
        entry_edge: int,
        goal: Point,
        clockwise: bool,
        net_id: Optional[int]
    ) -> list[Point]:
        """
        Walk around a hull boundary until we can reach the goal.

        Args:
            hull: The hull to walk around
            entry_point: Where we entered the hull boundary
            entry_edge: Edge index where we entered
            goal: Ultimate destination
            clockwise: Walk direction (True=CW, False=CCW)
            net_id: Net ID for same-net routing

        Returns:
            List of waypoints along the hull boundary
        """
        path: list[Point] = []
        n = len(hull.points)

        # Start from the entry edge's endpoint
        if clockwise:
            # CW: walk in reverse vertex order
            current_vertex = entry_edge  # Start vertex of entry edge
            step = -1
        else:
            # CCW: walk in forward vertex order
            current_vertex = (entry_edge + 1) % n  # End vertex of entry edge
            step = 1

        # Add offset point near entry
        offset_pt = self._offset_from_hull(entry_point, hull, entry_edge)
        path.append(offset_pt)

        visited_vertices: set[int] = set()
        max_vertices = n + 2  # Allow slightly more than full loop

        for _ in range(max_vertices):
            if current_vertex in visited_vertices:
                break
            visited_vertices.add(current_vertex)

            vertex = hull.points[current_vertex]
            offset_vertex = self._offset_vertex(vertex, hull, current_vertex)
            path.append(offset_vertex)

            # Check if we can reach the goal from this vertex
            if self._can_reach(offset_vertex, goal, net_id):
                return path

            # Move to next vertex
            current_vertex = (current_vertex + step) % n

        return path

    def _offset_from_hull(self, point: Point, hull: LineChain, edge_idx: int) -> Point:
        """
        Offset a point away from the hull edge.

        Args:
            point: Point on or near the hull
            edge_idx: Index of the nearest edge

        Returns:
            Point offset outward from the hull
        """
        e1, e2 = hull.get_edge(edge_idx)

        # Edge direction and outward normal
        edge_dir = (e2 - e1).normalized()
        # For CCW polygon, outward normal is edge direction rotated 90° clockwise
        # Rotation: (dx, dy) -> (dy, -dx)
        outward = Point(edge_dir.y, -edge_dir.x)

        return point + outward * (self.half_width + self.corner_offset)

    def _offset_vertex(self, vertex: Point, hull: LineChain, vertex_idx: int) -> Point:
        """
        Offset a vertex outward from the hull corner.

        Args:
            vertex: Hull vertex
            hull: The hull
            vertex_idx: Index of the vertex

        Returns:
            Point offset outward from the corner
        """
        n = len(hull.points)
        prev_idx = (vertex_idx - 1) % n
        next_idx = (vertex_idx + 1) % n

        prev_pt = hull.points[prev_idx]
        next_pt = hull.points[next_idx]

        # Edge directions
        v1 = (vertex - prev_pt).normalized()  # Direction of edge before vertex
        v2 = (next_pt - vertex).normalized()  # Direction of edge after vertex

        # For CCW polygon, outward normal is edge direction rotated 90° clockwise
        # Rotation: (dx, dy) -> (dy, -dx)
        n1 = Point(v1.y, -v1.x)  # Outward normal for edge before vertex
        n2 = Point(v2.y, -v2.x)  # Outward normal for edge after vertex

        # Average the normals to get outward direction at vertex
        outward = (n1 + n2).normalized()

        # If outward is zero (180-degree angle), use perpendicular to edge
        if outward.length() < 0.01:
            outward = n1

        # Offset by half width + corner offset
        offset = self.half_width + self.corner_offset
        return vertex + outward * offset

    def _can_reach(self, start: Point, end: Point, net_id: Optional[int]) -> bool:
        """Check if we can reach end from start without obstruction."""
        blocking = self._find_first_blocking_hull(start, end, net_id)
        return blocking is None

    def _choose_best_path(
        self,
        cw_path: list[Point],
        ccw_path: list[Point],
        goal: Point
    ) -> Optional[list[Point]]:
        """
        Choose the better of two walkaround paths.

        Prefers the shorter path that ends closer to the goal.
        """
        cw_valid = len(cw_path) > 0
        ccw_valid = len(ccw_path) > 0

        if not cw_valid and not ccw_valid:
            return None

        if not cw_valid:
            return ccw_path

        if not ccw_valid:
            return cw_path

        # Both valid - compare path lengths
        cw_len = self._path_length(cw_path)
        ccw_len = self._path_length(ccw_path)

        # Add distance to goal from path end
        cw_total = cw_len + cw_path[-1].distance_to(goal)
        ccw_total = ccw_len + ccw_path[-1].distance_to(goal)

        return cw_path if cw_total <= ccw_total else ccw_path

    def _path_length(self, path: list[Point]) -> float:
        """Calculate total length of a path."""
        if len(path) < 2:
            return 0.0
        total = 0.0
        for i in range(len(path) - 1):
            total += path[i].distance_to(path[i + 1])
        return total

    def _try_escape(
        self,
        current: Point,
        hull: IndexedHull,
        goal: Point
    ) -> Optional[Point]:
        """
        Try to escape when stuck in a loop with a hull.

        Attempts to move perpendicular to the goal direction.
        """
        # Direction to goal
        to_goal = goal - current
        dist = to_goal.length()
        if dist < 0.01:
            return None

        # Try perpendicular directions
        perp1 = Point(-to_goal.y / dist, to_goal.x / dist)
        perp2 = Point(to_goal.y / dist, -to_goal.x / dist)

        escape_dist = self.half_width * 3

        for perp in [perp1, perp2]:
            escape = current + perp * escape_dist
            # Check if escape point is clear
            if not self.hull_map.point_inside_any_hull(escape, hull.net_id):
                return escape

        return None


def walkaround_route(
    hull_map: HullMap,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    trace_width: float,
    net_id: Optional[int] = None,
    max_iterations: int = 1000
) -> list[tuple[float, float]]:
    """
    Convenience function for walkaround routing.

    Args:
        hull_map: Hull map for the layer
        start_x, start_y: Start position
        end_x, end_y: End position
        trace_width: Trace width
        net_id: Net ID for same-net routing
        max_iterations: Maximum iterations

    Returns:
        List of (x, y) waypoints, or empty list if no route found
    """
    router = WalkaroundRouter(hull_map, trace_width, max_iterations)
    result = router.route(Point(start_x, start_y), Point(end_x, end_y), net_id)

    if result.success:
        return [p.to_tuple() for p in result.path]
    return []
