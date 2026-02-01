"""Hull data structures for walkaround routing."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Point:
    """2D point with basic vector operations."""
    x: float
    y: float

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def dot(self, other: Point) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Point) -> float:
        """2D cross product (returns scalar z-component)."""
        return self.x * other.y - self.y * other.x

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> Point:
        ln = self.length()
        if ln < 1e-10:
            return Point(0, 0)
        return Point(self.x / ln, self.y / ln)

    def perpendicular(self) -> Point:
        """Return perpendicular vector (90 degrees CCW)."""
        return Point(-self.y, self.x)

    def distance_to(self, other: Point) -> float:
        return (self - other).length()

    def __iter__(self):
        yield self.x
        yield self.y

    def to_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class LineChain:
    """
    Closed polyline representing a hull boundary.

    Points are stored in CCW order. The chain is implicitly closed
    (last point connects back to first).
    """
    points: list[Point]
    net_id: int = 0  # Net this hull belongs to (for same-net filtering)

    def __len__(self) -> int:
        return len(self.points)

    def get_edge(self, i: int) -> tuple[Point, Point]:
        """Get edge from point i to point (i+1) mod n."""
        n = len(self.points)
        return (self.points[i], self.points[(i + 1) % n])

    def edges(self):
        """Iterate over all edges as (start, end) pairs."""
        n = len(self.points)
        for i in range(n):
            yield (self.points[i], self.points[(i + 1) % n])

    def point_inside(self, p: Point) -> bool:
        """
        Test if point is inside the closed polygon using ray casting.

        Returns True if inside (including on edge for practical purposes).
        """
        n = len(self.points)
        if n < 3:
            return False

        inside = False
        j = n - 1

        for i in range(n):
            pi = self.points[i]
            pj = self.points[j]

            # Ray casting: count intersections with horizontal ray from p
            if ((pi.y > p.y) != (pj.y > p.y) and
                p.x < (pj.x - pi.x) * (p.y - pi.y) / (pj.y - pi.y) + pi.x):
                inside = not inside
            j = i

        return inside

    def intersects_segment(self, p1: Point, p2: Point) -> list[tuple[Point, int]]:
        """
        Find all intersection points between a line segment and this hull.

        Args:
            p1, p2: Endpoints of the query segment

        Returns:
            List of (intersection_point, edge_index) sorted by distance from p1
        """
        intersections = []

        for i, (e1, e2) in enumerate(self.edges()):
            pt = segment_segment_intersection(p1, p2, e1, e2)
            if pt is not None:
                intersections.append((pt, i))

        # Sort by distance from p1
        intersections.sort(key=lambda x: (x[0] - p1).length_sq())
        return intersections

    def find_closest_point_on_boundary(self, p: Point) -> tuple[Point, int, float]:
        """
        Find the closest point on the hull boundary to the given point.

        Returns:
            (closest_point, edge_index, parameter_t along that edge)
        """
        best_dist_sq = float('inf')
        best_point = self.points[0]
        best_edge = 0
        best_t = 0.0

        for i, (e1, e2) in enumerate(self.edges()):
            closest, t = closest_point_on_segment(p, e1, e2)
            dist_sq = (closest - p).length_sq()
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_point = closest
                best_edge = i
                best_t = t

        return (best_point, best_edge, best_t)

    def segment_to_boundary_distance(self, p1: Point, p2: Point) -> tuple[float, Point, int]:
        """
        Find the minimum distance from a line segment to the hull boundary.

        Args:
            p1, p2: Segment endpoints

        Returns:
            (min_distance, closest_point_on_hull, edge_index)
        """
        min_dist_sq = float('inf')
        closest_point = self.points[0]
        closest_edge = 0

        # Check distance from segment to each hull edge
        for i, (e1, e2) in enumerate(self.edges()):
            # Find minimum distance between segments (p1, p2) and (e1, e2)
            dist_sq, pt = _segment_segment_distance_sq(p1, p2, e1, e2)
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_point = pt
                closest_edge = i

        return (min_dist_sq ** 0.5, closest_point, closest_edge)

    def centroid(self) -> Point:
        """Calculate centroid of the polygon."""
        if not self.points:
            return Point(0, 0)
        cx = sum(p.x for p in self.points) / len(self.points)
        cy = sum(p.y for p in self.points) / len(self.points)
        return Point(cx, cy)


def segment_segment_intersection(
    p1: Point, p2: Point,
    p3: Point, p4: Point,
    epsilon: float = 1e-10
) -> Optional[Point]:
    """
    Find intersection point of two line segments.

    Args:
        p1, p2: First segment endpoints
        p3, p4: Second segment endpoints
        epsilon: Tolerance for parallel/coincident detection

    Returns:
        Intersection point or None if segments don't intersect
    """
    d1 = p2 - p1  # Direction of first segment
    d2 = p4 - p3  # Direction of second segment
    d3 = p3 - p1

    cross = d1.cross(d2)

    # Check if segments are parallel
    if abs(cross) < epsilon:
        return None

    # Calculate intersection parameters
    t = d3.cross(d2) / cross
    u = d3.cross(d1) / cross

    # Check if intersection is within both segments
    if 0 <= t <= 1 and 0 <= u <= 1:
        return p1 + d1 * t

    return None


def closest_point_on_segment(p: Point, a: Point, b: Point) -> tuple[Point, float]:
    """
    Find closest point on segment ab to point p.

    Returns:
        (closest_point, parameter_t where 0=at a, 1=at b)
    """
    ab = b - a
    length_sq = ab.length_sq()

    if length_sq < 1e-10:
        return (a, 0.0)

    t = (p - a).dot(ab) / length_sq
    t = max(0.0, min(1.0, t))

    return (a + ab * t, t)


def point_to_segment_distance(p: Point, a: Point, b: Point) -> float:
    """Calculate shortest distance from point p to segment ab."""
    closest, _ = closest_point_on_segment(p, a, b)
    return p.distance_to(closest)


def _segment_segment_distance_sq(p1: Point, p2: Point, p3: Point, p4: Point) -> tuple[float, Point]:
    """
    Calculate the squared minimum distance between two line segments.

    Args:
        p1, p2: First segment endpoints
        p3, p4: Second segment endpoints

    Returns:
        (squared_distance, closest_point_on_second_segment)
    """
    # Check all four endpoint-to-segment distances
    candidates = []

    # p1 to segment (p3, p4)
    c1, _ = closest_point_on_segment(p1, p3, p4)
    candidates.append(((p1 - c1).length_sq(), c1))

    # p2 to segment (p3, p4)
    c2, _ = closest_point_on_segment(p2, p3, p4)
    candidates.append(((p2 - c2).length_sq(), c2))

    # p3 to segment (p1, p2)
    c3, _ = closest_point_on_segment(p3, p1, p2)
    candidates.append(((p3 - c3).length_sq(), p3))

    # p4 to segment (p1, p2)
    c4, _ = closest_point_on_segment(p4, p1, p2)
    candidates.append(((p4 - c4).length_sq(), p4))

    # Return the minimum
    return min(candidates, key=lambda x: x[0])


class HullGenerator:
    """Factory class for generating hulls from PCB elements."""

    @staticmethod
    def octagonal_hull(
        center: Point,
        half_width: float,
        half_height: float,
        clearance: float,
        chamfer_ratio: float = 0.3
    ) -> LineChain:
        """
        Create an octagonal hull around a rectangular pad.

        The octagon is created by chamfering the corners of a rectangle.

        Shape (CCW from bottom-left going clockwise visually):
            (-hw+c, -hh)-----(hw-c, -hh)
           /                             \\
        (-hw, -hh+c)                    (hw, -hh+c)
          |                               |
        (-hw, hh-c)                     (hw, hh-c)
           \\                             /
            (-hw+c, hh)-------(hw-c, hh)

        Args:
            center: Center point
            half_width: Half of pad width
            half_height: Half of pad height
            clearance: Additional clearance to add
            chamfer_ratio: Ratio of chamfer size (0-0.5)

        Returns:
            LineChain with 8 vertices in CCW order
        """
        # Expand by clearance
        hw = half_width + clearance
        hh = half_height + clearance

        # Chamfer size is proportional to the smaller dimension
        chamfer = min(hw, hh) * min(chamfer_ratio, 0.5)

        cx, cy = center.x, center.y

        # 8 vertices in CCW order (starting from bottom-left, going CCW)
        points = [
            Point(cx - hw + chamfer, cy - hh),      # Bottom edge left
            Point(cx + hw - chamfer, cy - hh),      # Bottom edge right
            Point(cx + hw, cy - hh + chamfer),      # Right edge bottom
            Point(cx + hw, cy + hh - chamfer),      # Right edge top
            Point(cx + hw - chamfer, cy + hh),      # Top edge right
            Point(cx - hw + chamfer, cy + hh),      # Top edge left
            Point(cx - hw, cy + hh - chamfer),      # Left edge top
            Point(cx - hw, cy - hh + chamfer),      # Left edge bottom
        ]

        return LineChain(points=points)

    @staticmethod
    def circular_hull(
        center: Point,
        radius: float,
        clearance: float,
        num_segments: int = 16
    ) -> LineChain:
        """
        Create a circular hull approximated by a polygon.

        Args:
            center: Center point
            radius: Radius of the circle
            clearance: Additional clearance to add
            num_segments: Number of polygon segments (more = smoother)

        Returns:
            LineChain approximating a circle
        """
        r = radius + clearance
        points = []

        for i in range(num_segments):
            angle = 2 * math.pi * i / num_segments
            x = center.x + r * math.cos(angle)
            y = center.y + r * math.sin(angle)
            points.append(Point(x, y))

        return LineChain(points=points)

    @staticmethod
    def segment_hull(
        start: Point,
        end: Point,
        width: float,
        clearance: float,
        end_segments: int = 4
    ) -> LineChain:
        """
        Create a stadium-shaped (capsule) hull around a trace segment.

        The hull consists of:
        - Two parallel lines offset from the segment
        - Semicircular caps at each end

        Points are in CCW order (interior on left when traversing).

        Args:
            start: Start point of segment
            end: End point of segment
            width: Trace width
            clearance: Additional clearance to add
            end_segments: Number of segments for each semicircular cap

        Returns:
            LineChain forming a capsule shape in CCW order
        """
        half_width = width / 2 + clearance

        # Direction vector
        direction = end - start
        length = direction.length()

        if length < 1e-10:
            # Degenerate to circle
            return HullGenerator.circular_hull(start, width / 2, clearance)

        # Normalized direction and perpendicular
        dir_norm = direction.normalized()
        perp = dir_norm.perpendicular()

        points = []

        # Build hull in CW order first, then reverse for CCW
        # Left side (going from start to end, offset to the left)
        points.append(start + perp * half_width)
        points.append(end + perp * half_width)

        # End cap (semicircle at end point, going from left to right via front)
        for i in range(1, end_segments + 1):
            angle = math.pi / 2 - math.pi * i / end_segments
            offset = dir_norm * (half_width * math.cos(angle)) + perp * (half_width * math.sin(angle))
            points.append(end + offset)

        # Right side (going from end back to start, offset to the right)
        points.append(start - perp * half_width)

        # Start cap (semicircle at start point, going from right to left via back)
        for i in range(1, end_segments + 1):
            angle = -math.pi / 2 - math.pi * i / end_segments
            offset = dir_norm * (half_width * math.cos(angle)) + perp * (half_width * math.sin(angle))
            points.append(start + offset)

        # Remove the last point if it duplicates the first (closing the loop)
        if len(points) > 1 and abs(points[-1].x - points[0].x) < 1e-10 and abs(points[-1].y - points[0].y) < 1e-10:
            points.pop()

        # Reverse to get CCW order
        points.reverse()

        return LineChain(points=points)

    @staticmethod
    def rotated_rect_hull(
        center: Point,
        half_width: float,
        half_height: float,
        angle_deg: float,
        clearance: float,
        chamfer_ratio: float = 0.3
    ) -> LineChain:
        """
        Create an octagonal hull for a rotated rectangular pad.

        Args:
            center: Center point
            half_width: Half of pad width (before rotation)
            half_height: Half of pad height (before rotation)
            angle_deg: Rotation angle in degrees
            clearance: Additional clearance to add
            chamfer_ratio: Ratio of chamfer size

        Returns:
            LineChain with 8 vertices, rotated
        """
        # First create axis-aligned octagon
        hull = HullGenerator.octagonal_hull(
            Point(0, 0),  # Create at origin
            half_width,
            half_height,
            clearance,
            chamfer_ratio
        )

        # Rotate all points
        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_points = []
        for p in hull.points:
            rx = p.x * cos_a - p.y * sin_a + center.x
            ry = p.x * sin_a + p.y * cos_a + center.y
            rotated_points.append(Point(rx, ry))

        return LineChain(points=rotated_points)

    @staticmethod
    def via_hull(center: Point, size: float, clearance: float) -> LineChain:
        """
        Create a circular hull for a via.

        Args:
            center: Via center
            size: Via outer diameter
            clearance: Additional clearance

        Returns:
            Circular LineChain
        """
        return HullGenerator.circular_hull(center, size / 2, clearance)
