"""Path optimization for routed traces."""
from __future__ import annotations
import math
from typing import Optional

from backend.routing.hulls import Point, LineChain
from backend.routing.hull_map import HullMap


class PathOptimizer:
    """
    Optimizes routed paths for cleaner traces.

    Operations:
    1. Merge colinear segments
    2. Smooth obtuse corners
    3. Snap to 45-degree angles
    4. Remove redundant points
    """

    def __init__(
        self,
        hull_map: Optional[HullMap] = None,
        trace_width: float = 0.2,
        angle_tolerance: float = 5.0,  # degrees
        snap_threshold: float = 10.0,  # degrees from 45-degree multiple
    ):
        """
        Initialize path optimizer.

        Args:
            hull_map: Optional hull map for collision checking during optimization
            trace_width: Trace width for clearance checking
            angle_tolerance: Tolerance for considering segments colinear (degrees)
            snap_threshold: Angle threshold for snapping to 45-degree multiples
        """
        self.hull_map = hull_map
        self.trace_width = trace_width
        self.angle_tolerance = math.radians(angle_tolerance)
        self.snap_threshold = math.radians(snap_threshold)

    def optimize(
        self,
        path: list[tuple[float, float]],
        net_id: Optional[int] = None
    ) -> list[tuple[float, float]]:
        """
        Optimize a path through multiple passes.

        Args:
            path: List of (x, y) waypoints
            net_id: Net ID for collision checking

        Returns:
            Optimized path
        """
        if len(path) < 2:
            return path

        # Convert to Points for easier manipulation
        points = [Point(x, y) for x, y in path]

        # Pass 1: Remove duplicate/very close points
        points = self._remove_duplicates(points)

        # Pass 2: Merge colinear segments
        points = self._merge_colinear(points)

        # Pass 3: Try to smooth corners by shortcutting
        if self.hull_map is not None:
            points = self._smooth_corners(points, net_id)

        # Pass 4: Snap to 45-degree angles where possible
        if self.hull_map is not None:
            points = self._snap_to_45(points, net_id)

        # Pass 5: Final colinear merge
        points = self._merge_colinear(points)

        return [p.to_tuple() for p in points]

    def _remove_duplicates(self, points: list[Point], epsilon: float = 0.001) -> list[Point]:
        """Remove duplicate or nearly-duplicate consecutive points."""
        if len(points) < 2:
            return points

        result = [points[0]]
        for p in points[1:]:
            if p.distance_to(result[-1]) > epsilon:
                result.append(p)

        return result

    def _merge_colinear(self, points: list[Point]) -> list[Point]:
        """Merge consecutive colinear segments."""
        if len(points) < 3:
            return points

        result = [points[0]]

        i = 1
        while i < len(points) - 1:
            prev = result[-1]
            curr = points[i]
            next_pt = points[i + 1]

            # Calculate angles
            angle1 = math.atan2(curr.y - prev.y, curr.x - prev.x)
            angle2 = math.atan2(next_pt.y - curr.y, next_pt.x - curr.x)

            # Normalize angle difference to [-pi, pi]
            diff = angle2 - angle1
            while diff > math.pi:
                diff -= 2 * math.pi
            while diff < -math.pi:
                diff += 2 * math.pi

            if abs(diff) > self.angle_tolerance:
                # Not colinear, keep the point
                result.append(curr)

            i += 1

        result.append(points[-1])
        return result

    def _smooth_corners(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Try to smooth corners by taking shortcuts.

        For each corner, try to skip it if the direct path is clear.
        """
        if len(points) < 3 or self.hull_map is None:
            return points

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            # Try to skip as many intermediate points as possible
            best_j = i + 1

            for j in range(i + 2, len(points)):
                if self._path_clear(result[-1], points[j], net_id):
                    best_j = j

            result.append(points[best_j])
            i = best_j

        return result

    def _snap_to_45(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Snap segments to 45-degree angle multiples where possible.

        For each segment, check if snapping to nearest 45° is valid.
        """
        if len(points) < 2 or self.hull_map is None:
            return points

        result = [points[0]]

        for i in range(1, len(points)):
            prev = result[-1]
            curr = points[i]

            # Current angle
            dx = curr.x - prev.x
            dy = curr.y - prev.y
            angle = math.atan2(dy, dx)

            # Find nearest 45-degree multiple
            snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)

            # Check if within threshold
            if abs(angle - snap_angle) <= self.snap_threshold:
                # Try to snap
                length = math.sqrt(dx * dx + dy * dy)
                snapped = Point(
                    prev.x + length * math.cos(snap_angle),
                    prev.y + length * math.sin(snap_angle)
                )

                # Check if snapped position is valid
                if self._path_clear(prev, snapped, net_id):
                    # Also check if we can continue from snapped to next point
                    if i == len(points) - 1 or self._path_clear(snapped, points[i], net_id):
                        result.append(snapped)
                        continue

            result.append(curr)

        return result

    def _path_clear(self, start: Point, end: Point, net_id: Optional[int]) -> bool:
        """Check if a path between two points is clear of obstacles."""
        if self.hull_map is None:
            return True

        blocking = self.hull_map.get_blocking_hulls(
            start, end, self.trace_width, net_id
        )
        return len(blocking) == 0

    def merge_colinear_simple(
        self,
        path: list[tuple[float, float]],
        tolerance: float = 0.001
    ) -> list[tuple[float, float]]:
        """
        Simple colinear merge without angle calculations.

        Uses cross product to check if three points are colinear.

        Args:
            path: Input path
            tolerance: Colinearity tolerance

        Returns:
            Path with colinear points removed
        """
        if len(path) < 3:
            return path

        result = [path[0]]

        for i in range(1, len(path) - 1):
            prev = result[-1]
            curr = path[i]
            next_pt = path[i + 1]

            # Cross product to check colinearity
            cross = ((curr[0] - prev[0]) * (next_pt[1] - prev[1]) -
                     (curr[1] - prev[1]) * (next_pt[0] - prev[0]))

            if abs(cross) > tolerance:
                result.append(curr)

        result.append(path[-1])
        return result


def optimize_path(
    path: list[tuple[float, float]],
    hull_map: Optional[HullMap] = None,
    trace_width: float = 0.2,
    net_id: Optional[int] = None
) -> list[tuple[float, float]]:
    """
    Convenience function for path optimization.

    Args:
        path: Input path as list of (x, y) tuples
        hull_map: Optional hull map for collision checking
        trace_width: Trace width
        net_id: Net ID for same-net routing

    Returns:
        Optimized path
    """
    optimizer = PathOptimizer(hull_map, trace_width)
    return optimizer.optimize(path, net_id)
