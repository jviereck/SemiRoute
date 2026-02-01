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

        # Pass 2: Force all segments to 45-degree angles
        points = self._enforce_45_degrees(points, net_id)

        # Pass 3: Merge colinear segments
        points = self._merge_colinear(points)

        # Pass 4: Remove backtrack/indent patterns
        if self.hull_map is not None:
            points = self._remove_backtracks(points, net_id)

        # Pass 5: Eliminate direction reversals (both X and Y)
        if self.hull_map is not None:
            points = self._eliminate_axis_reversals(points, net_id, axis='x')
            points = self._eliminate_axis_reversals(points, net_id, axis='y')

        # Pass 6: Try to smooth corners by shortcutting (only with 45° paths)
        if self.hull_map is not None:
            points = self._smooth_corners_45(points, net_id)

        # Pass 7: Minimize direction changes
        if self.hull_map is not None:
            points = self._minimize_direction_changes(points, net_id)

        # Pass 8: Remove short jitter segments
        if self.hull_map is not None:
            points = self._remove_short_segments(points, net_id)

        # Pass 9: Final colinear merge
        points = self._merge_colinear(points)

        return [p.to_tuple() for p in points]

    def _remove_duplicates(self, points: list[Point], epsilon: float = 0.05) -> list[Point]:
        """Remove duplicate or nearly-duplicate consecutive points."""
        if len(points) < 2:
            return points

        result = [points[0]]
        for i, p in enumerate(points[1:], 1):
            # Always keep the last point
            if i == len(points) - 1:
                if p.distance_to(result[-1]) > 0.001:  # Only skip true duplicates for endpoint
                    result.append(p)
            elif p.distance_to(result[-1]) > epsilon:
                result.append(p)

        # Ensure we have at least start and end
        if len(result) == 1 and len(points) > 1:
            result.append(points[-1])

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

    def _remove_backtracks(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Remove backtrack/indent patterns where the path reverses direction.

        Detects patterns like: NW -> E -> N -> NW (indent around obstacle)
        and tries to replace with more direct paths.
        """
        if len(points) < 4 or self.hull_map is None:
            return points

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            # Try to find a simpler path from current point to later points
            best_j = i + 1
            best_path: list[Point] = []
            best_savings = 0.0

            # Look ahead up to 8 points for potential shortcuts (increased from 5)
            for j in range(i + 2, min(i + 9, len(points))):
                start = result[-1]
                end = points[j]

                # Try direct path first
                if self._path_clear(start, end, net_id):
                    dx = end.x - start.x
                    dy = end.y - start.y
                    if self._is_45_degree_angle(dx, dy):
                        # Direct 45° path - calculate savings
                        direct_len = start.distance_to(end)
                        original_len = self._path_length(points[i:j+1])
                        savings = original_len - direct_len
                        if savings > best_savings:
                            best_j = j
                            best_path = []
                            best_savings = savings
                        continue

                # Try single-midpoint dogleg
                mid = self._find_best_midpoint(start, end, net_id)
                if mid is not None:
                    # Check if this is shorter than going through all intermediate points
                    direct_len = start.distance_to(mid) + mid.distance_to(end)
                    original_len = self._path_length(points[i:j+1])
                    savings = original_len - direct_len
                    if savings > best_savings and savings > 0.01:  # At least some savings
                        best_j = j
                        best_path = [mid]
                        best_savings = savings

            # Add the best path found
            for p in best_path:
                result.append(p)
            result.append(points[best_j])
            i = best_j

        return result

    def _path_length(self, points: list[Point]) -> float:
        """Calculate total length of a path."""
        if len(points) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(points)):
            total += points[i].distance_to(points[i-1])
        return total

    def _eliminate_axis_reversals(
        self,
        points: list[Point],
        net_id: Optional[int],
        axis: str = 'x'
    ) -> list[Point]:
        """
        Eliminate segments that go against the overall direction on a given axis.

        Args:
            points: Path points
            net_id: Net ID for collision checking
            axis: 'x' or 'y' - which axis to check for reversals

        If the path goes in the positive direction overall, eliminate negative segments.
        If the path goes in the negative direction overall, eliminate positive segments.
        """
        if len(points) < 3 or self.hull_map is None:
            return points

        # Helper to get coordinate on the specified axis
        def get_coord(p: Point) -> float:
            return p.x if axis == 'x' else p.y

        # Determine overall direction on this axis
        overall_delta = get_coord(points[-1]) - get_coord(points[0])
        if abs(overall_delta) < 0.1:
            # No significant movement on this axis, skip
            return points

        going_positive = overall_delta > 0

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            curr = result[-1]
            next_pt = points[i + 1]

            # Check if this segment goes against the overall direction
            seg_delta = get_coord(next_pt) - get_coord(curr)
            is_reversal = ((going_positive and seg_delta < -0.05) or
                          (not going_positive and seg_delta > 0.05))

            if is_reversal and i < len(points) - 2:
                # Found a reversal - try to skip ahead to a point that doesn't reverse
                best_j = i + 1
                best_path: list[Point] = []

                for j in range(i + 2, min(i + 10, len(points))):
                    end = points[j]
                    end_delta = get_coord(end) - get_coord(curr)

                    # Check if going to this point would eliminate the reversal
                    end_is_ok = ((going_positive and end_delta >= -0.05) or
                                (not going_positive and end_delta <= 0.05))

                    if end_is_ok:
                        # Try direct path
                        if self._path_clear(curr, end, net_id):
                            dx = end.x - curr.x
                            dy = end.y - curr.y
                            if self._is_45_degree_angle(dx, dy):
                                best_j = j
                                best_path = []
                                break

                        # Try midpoint alternatives
                        mid_candidates = self._generate_non_reversing_midpoints_generic(
                            curr, end, going_positive, axis
                        )
                        for mid in mid_candidates:
                            if (self._path_clear(curr, mid, net_id) and
                                self._path_clear(mid, end, net_id)):
                                dx1 = mid.x - curr.x
                                dy1 = mid.y - curr.y
                                dx2 = end.x - mid.x
                                dy2 = end.y - mid.y
                                if (self._is_45_degree_angle(dx1, dy1) and
                                    self._is_45_degree_angle(dx2, dy2)):
                                    # Check mid doesn't reverse on this axis
                                    mid_delta = get_coord(mid) - get_coord(curr)
                                    mid_ok = ((going_positive and mid_delta >= -0.05) or
                                             (not going_positive and mid_delta <= 0.05))
                                    if mid_ok:
                                        best_j = j
                                        best_path = [mid]
                                        break
                        if best_path:
                            break

                for p in best_path:
                    result.append(p)
                result.append(points[best_j])
                i = best_j
            else:
                result.append(next_pt)
                i += 1

        return result

    def _generate_non_reversing_midpoints_generic(
        self,
        start: Point,
        end: Point,
        going_positive: bool,
        axis: str = 'x'
    ) -> list[Point]:
        """Generate midpoint candidates that don't reverse on the specified axis."""
        candidates = []
        dx = end.x - start.x
        dy = end.y - start.y
        adx = abs(dx)
        ady = abs(dy)

        if axis == 'x':
            # Avoiding X reversal - prefer vertical movement first
            if ady > adx:
                # More vertical movement - go vertical first
                vert_dist = ady - adx
                mid_y = start.y + vert_dist * (1 if dy > 0 else -1)
                candidates.append(Point(start.x, mid_y))

            # Try diagonal that doesn't reverse X
            diag = min(adx, ady)
            diag_dx = diag * (1 if dx > 0 else -1)
            diag_dy = diag * (1 if dy > 0 else -1)
            if (going_positive and diag_dx >= 0) or (not going_positive and diag_dx <= 0):
                candidates.append(Point(start.x + diag_dx, start.y + diag_dy))

            # Try going to end's X first (vertical segment)
            if adx < ady:
                candidates.append(Point(start.x, end.y - (ady - adx) * (1 if dy > 0 else -1)))
        else:
            # Avoiding Y reversal - prefer horizontal movement first
            if adx > ady:
                # More horizontal movement - go horizontal first
                horiz_dist = adx - ady
                mid_x = start.x + horiz_dist * (1 if dx > 0 else -1)
                candidates.append(Point(mid_x, start.y))

            # Try diagonal that doesn't reverse Y
            diag = min(adx, ady)
            diag_dx = diag * (1 if dx > 0 else -1)
            diag_dy = diag * (1 if dy > 0 else -1)
            if (going_positive and diag_dy >= 0) or (not going_positive and diag_dy <= 0):
                candidates.append(Point(start.x + diag_dx, start.y + diag_dy))

            # Try going to end's Y first (horizontal segment)
            if ady < adx:
                candidates.append(Point(end.x - (adx - ady) * (1 if dx > 0 else -1), start.y))

        return candidates

    def _minimize_direction_changes(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Minimize the number of direction changes in the path.

        For each triplet of points A-B-C where direction changes at B,
        try to find an alternative that eliminates or reduces the turn.
        """
        if len(points) < 3 or self.hull_map is None:
            return points

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            if i >= len(points) - 2:
                result.append(points[i + 1])
                i += 1
                continue

            curr = result[-1]
            next_pt = points[i + 1]
            after = points[i + 2]

            # Calculate current direction and next direction
            dx1 = next_pt.x - curr.x
            dy1 = next_pt.y - curr.y
            dx2 = after.x - next_pt.x
            dy2 = after.y - next_pt.y

            angle1 = math.atan2(dy1, dx1)
            angle2 = math.atan2(dy2, dx2)
            angle_diff = abs(angle2 - angle1)
            if angle_diff > math.pi:
                angle_diff = 2 * math.pi - angle_diff

            # If there's a significant direction change, try to simplify
            if angle_diff > math.radians(30):
                # Try going directly from curr to after
                if self._path_clear(curr, after, net_id):
                    dx = after.x - curr.x
                    dy = after.y - curr.y
                    if self._is_45_degree_angle(dx, dy):
                        # Skip the intermediate point
                        result.append(after)
                        i += 2
                        continue

                # Try a single dogleg from curr to after
                mid = self._find_best_midpoint(curr, after, net_id)
                if mid is not None:
                    result.append(mid)
                    result.append(after)
                    i += 2
                    continue

            # No simplification found, keep the point
            result.append(next_pt)
            i += 1

        # Add final point if not already added
        if result[-1] != points[-1]:
            result.append(points[-1])

        return result

    def _find_best_midpoint(self, start: Point, end: Point, net_id: Optional[int]) -> Optional[Point]:
        """
        Find the best midpoint for a dogleg that minimizes path length.

        Tries multiple candidate midpoints and returns the one that gives
        the shortest valid path.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        adx = abs(dx)
        ady = abs(dy)

        candidates = []

        # Generate candidate midpoints for different dogleg patterns
        if adx >= ady:
            # Horizontal dominant
            # Option 1: Diagonal first
            diag = ady
            mid1 = Point(start.x + diag * (1 if dx > 0 else -1),
                        start.y + diag * (1 if dy > 0 else -1))
            # Option 2: Horizontal first
            horiz = adx - ady
            mid2 = Point(start.x + horiz * (1 if dx > 0 else -1), start.y)
            candidates.extend([mid1, mid2])
        else:
            # Vertical dominant
            # Option 1: Diagonal first
            diag = adx
            mid1 = Point(start.x + diag * (1 if dx > 0 else -1),
                        start.y + diag * (1 if dy > 0 else -1))
            # Option 2: Vertical first
            vert = ady - adx
            mid2 = Point(start.x, start.y + vert * (1 if dy > 0 else -1))
            candidates.extend([mid1, mid2])

        # Also try midpoints that go to end's x or y first
        mid3 = Point(end.x, start.y)  # Go to end's x first
        mid4 = Point(start.x, end.y)  # Go to end's y first
        candidates.extend([mid3, mid4])

        # Find shortest valid path
        best_mid = None
        best_len = float('inf')

        for mid in candidates:
            # Check both segments are at 45° and clear
            dx1 = mid.x - start.x
            dy1 = mid.y - start.y
            dx2 = end.x - mid.x
            dy2 = end.y - mid.y

            if not self._is_45_degree_angle(dx1, dy1):
                continue
            if not self._is_45_degree_angle(dx2, dy2):
                continue
            if not self._path_clear(start, mid, net_id):
                continue
            if not self._path_clear(mid, end, net_id):
                continue

            path_len = start.distance_to(mid) + mid.distance_to(end)
            if path_len < best_len:
                best_len = path_len
                best_mid = mid

        return best_mid

    def _detect_backtrack(self, p1: Point, p2: Point, p3: Point) -> bool:
        """
        Detect if moving from p1->p2->p3 involves a backtrack.

        A backtrack occurs when the direction from p2->p3 has a component
        that is opposite to the direction from p1->p2.
        """
        dx1 = p2.x - p1.x
        dy1 = p2.y - p1.y
        dx2 = p3.x - p2.x
        dy2 = p3.y - p2.y

        # Check if x or y direction reverses
        x_reverses = (dx1 > 0.01 and dx2 < -0.01) or (dx1 < -0.01 and dx2 > 0.01)
        y_reverses = (dy1 > 0.01 and dy2 < -0.01) or (dy1 < -0.01 and dy2 > 0.01)

        return x_reverses or y_reverses

    def _enforce_45_degrees(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Convert all segments to use only 45-degree angle multiples.

        For each segment not at a 45° multiple, insert an intermediate point
        to create two segments that are both at 45° multiples.
        """
        if len(points) < 2:
            return points

        result = [points[0]]

        for i in range(1, len(points)):
            prev = result[-1]
            curr = points[i]

            dx = curr.x - prev.x
            dy = curr.y - prev.y

            # Check if already at 45° multiple
            if self._is_45_degree_angle(dx, dy):
                result.append(curr)
                continue

            # Need to convert to 45° segments
            # Strategy: use horizontal/vertical + 45° diagonal, or vice versa
            mid_point = self._compute_45_midpoint(prev, curr, net_id)

            if mid_point is not None:
                result.append(mid_point)

            result.append(curr)

        return result

    def _is_45_degree_angle(self, dx: float, dy: float, tolerance: float = 0.01) -> bool:
        """Check if a direction vector is at a 45-degree multiple."""
        if abs(dx) < tolerance and abs(dy) < tolerance:
            return True  # Zero-length, doesn't matter

        # 45° multiples: 0°, 45°, 90°, 135°, 180°, etc.
        # At these angles: |dx| == |dy| (diagonal) or dx==0 or dy==0 (orthogonal)
        adx = abs(dx)
        ady = abs(dy)

        # Orthogonal (0° or 90°)
        if adx < tolerance or ady < tolerance:
            return True

        # Diagonal (45°)
        ratio = adx / ady if ady > tolerance else float('inf')
        if abs(ratio - 1.0) < tolerance:
            return True

        return False

    def _compute_45_midpoint(
        self,
        start: Point,
        end: Point,
        net_id: Optional[int]
    ) -> Optional[Point]:
        """
        Compute an intermediate point that creates two 45° segments.

        Uses the "dogleg" pattern: one orthogonal segment + one diagonal,
        or one diagonal + one orthogonal.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        adx = abs(dx)
        ady = abs(dy)

        # Determine which pattern to use based on aspect ratio
        # If more horizontal: horizontal first, then diagonal
        # If more vertical: vertical first, then diagonal

        candidates = []

        if adx >= ady:
            # More horizontal movement needed
            # Option 1: Go diagonal first, then horizontal
            diag_dist = ady  # Diagonal covers the y distance
            diag_dx = diag_dist * (1 if dx > 0 else -1)
            diag_dy = diag_dist * (1 if dy > 0 else -1)
            mid1 = Point(start.x + diag_dx, start.y + diag_dy)
            candidates.append(mid1)

            # Option 2: Go horizontal first, then diagonal
            horiz_dist = adx - ady
            mid2 = Point(start.x + horiz_dist * (1 if dx > 0 else -1), start.y)
            candidates.append(mid2)
        else:
            # More vertical movement needed
            # Option 1: Go diagonal first, then vertical
            diag_dist = adx
            diag_dx = diag_dist * (1 if dx > 0 else -1)
            diag_dy = diag_dist * (1 if dy > 0 else -1)
            mid1 = Point(start.x + diag_dx, start.y + diag_dy)
            candidates.append(mid1)

            # Option 2: Go vertical first, then diagonal
            vert_dist = ady - adx
            mid2 = Point(start.x, start.y + vert_dist * (1 if dy > 0 else -1))
            candidates.append(mid2)

        # Pick the first valid candidate (check for collisions if hull_map available)
        for mid in candidates:
            if self.hull_map is None:
                return mid
            # Check both segments are clear
            if (self._path_clear(start, mid, net_id) and
                self._path_clear(mid, end, net_id)):
                return mid

        # If no clear path, return first candidate anyway (let routing handle it)
        return candidates[0] if candidates else None

    def _remove_short_segments(
        self,
        points: list[Point],
        net_id: Optional[int],
        min_segment_length: float = 0.2
    ) -> list[Point]:
        """
        Remove short jitter segments by merging them with adjacent segments.

        For each segment shorter than min_segment_length, try to:
        1. Skip the intermediate point if direct path is valid (45°, collision-free)
        2. Adjust adjacent points to eliminate the jitter

        Args:
            points: Path points
            net_id: Net ID for collision checking
            min_segment_length: Minimum segment length to keep (mm)

        Returns:
            Path with short segments removed where possible
        """
        if len(points) < 3 or self.hull_map is None:
            return points

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            curr = result[-1]
            next_pt = points[i + 1]
            seg_len = curr.distance_to(next_pt)

            # Check if this is a short segment
            if seg_len < min_segment_length and i < len(points) - 2:
                # Try to skip this point and go directly to a later point
                best_j = i + 1
                best_path: list[Point] = []

                # Look ahead to find a point we can connect to directly
                for j in range(i + 2, min(i + 5, len(points))):
                    end = points[j]

                    # Try direct connection
                    if self._path_clear(curr, end, net_id):
                        dx = end.x - curr.x
                        dy = end.y - curr.y
                        if self._is_45_degree_angle(dx, dy):
                            best_j = j
                            best_path = []
                            break

                    # Try with one midpoint
                    mid = self._find_best_midpoint(curr, end, net_id)
                    if mid is not None:
                        # Check this midpoint isn't creating another short segment
                        if curr.distance_to(mid) >= min_segment_length:
                            best_j = j
                            best_path = [mid]
                            break

                # Use the best path found
                for p in best_path:
                    result.append(p)
                result.append(points[best_j])
                i = best_j
            else:
                result.append(next_pt)
                i += 1

        return result

    def _smooth_corners_45(self, points: list[Point], net_id: Optional[int]) -> list[Point]:
        """
        Try to smooth corners while maintaining 45° angles.

        For each corner, try to skip it if the direct path is clear AND at 45°.
        """
        if len(points) < 3 or self.hull_map is None:
            return points

        result = [points[0]]
        i = 0

        while i < len(points) - 1:
            # Try to skip as many intermediate points as possible
            best_j = i + 1

            for j in range(i + 2, len(points)):
                dx = points[j].x - result[-1].x
                dy = points[j].y - result[-1].y
                # Only shortcut if result is at 45° and path is clear
                if self._is_45_degree_angle(dx, dy) and self._path_clear(result[-1], points[j], net_id):
                    best_j = j

            result.append(points[best_j])
            i = best_j

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
