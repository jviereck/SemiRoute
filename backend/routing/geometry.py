"""Accurate geometry calculations for PCB elements."""
import math
from typing import Union, Optional

from backend.pcb.models import PadInfo, TraceInfo, ViaInfo


class GeometryChecker:
    """
    Accurate distance calculations for PCB element shapes.

    All methods return the distance from a point to the element edge:
    - Positive: point is outside the element
    - Negative: point is inside the element
    - Zero: point is exactly on the edge
    """

    @staticmethod
    def point_to_pad_distance(px: float, py: float, pad: PadInfo) -> float:
        """
        Calculate distance from point to pad edge, handling all shapes and rotation.

        Handles: circle, rect, roundrect, oval
        """
        # Transform point to pad's local coordinate system
        dx = px - pad.x
        dy = py - pad.y

        if pad.angle != 0:
            # Rotate point to align with pad axes (rotate by -angle)
            angle_rad = math.radians(-pad.angle)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            local_x = dx * cos_a - dy * sin_a
            local_y = dx * sin_a + dy * cos_a
        else:
            local_x, local_y = dx, dy

        # Half dimensions
        half_w = pad.width / 2
        half_h = pad.height / 2

        if pad.shape == 'circle':
            return GeometryChecker._point_to_circle(local_x, local_y, min(half_w, half_h))
        elif pad.shape == 'oval':
            return GeometryChecker._point_to_oval(local_x, local_y, half_w, half_h)
        elif pad.shape == 'roundrect':
            corner_radius = min(half_w, half_h) * pad.roundrect_ratio
            return GeometryChecker._point_to_roundrect(local_x, local_y, half_w, half_h, corner_radius)
        else:  # rect
            return GeometryChecker._point_to_rect(local_x, local_y, half_w, half_h)

    @staticmethod
    def _point_to_circle(x: float, y: float, radius: float) -> float:
        """Distance from point at (x,y) to circle centered at origin."""
        return math.sqrt(x * x + y * y) - radius

    @staticmethod
    def _point_to_rect(x: float, y: float, half_w: float, half_h: float) -> float:
        """Distance from point to axis-aligned rectangle centered at origin."""
        # Find distance to rectangle boundary
        if abs(x) <= half_w and abs(y) <= half_h:
            # Inside: return negative of distance to nearest edge
            dist_to_x_edge = half_w - abs(x)
            dist_to_y_edge = half_h - abs(y)
            return -min(dist_to_x_edge, dist_to_y_edge)

        # Outside: find closest point on boundary
        closest_x = max(-half_w, min(half_w, x))
        closest_y = max(-half_h, min(half_h, y))
        return math.sqrt((x - closest_x) ** 2 + (y - closest_y) ** 2)

    @staticmethod
    def _point_to_oval(x: float, y: float, half_w: float, half_h: float) -> float:
        """
        Distance from point to oval (stadium shape / discorectangle).

        Oval is two semicircles connected by straight sides.
        """
        if half_w > half_h:
            # Horizontal oval: semicircles at left and right
            radius = half_h
            cap_offset = half_w - radius
            if x < -cap_offset:
                # Left semicircle
                return math.sqrt((x + cap_offset) ** 2 + y ** 2) - radius
            elif x > cap_offset:
                # Right semicircle
                return math.sqrt((x - cap_offset) ** 2 + y ** 2) - radius
            else:
                # Middle rectangle portion
                return abs(y) - radius
        elif half_h > half_w:
            # Vertical oval: semicircles at top and bottom
            radius = half_w
            cap_offset = half_h - radius
            if y < -cap_offset:
                return math.sqrt(x ** 2 + (y + cap_offset) ** 2) - radius
            elif y > cap_offset:
                return math.sqrt(x ** 2 + (y - cap_offset) ** 2) - radius
            else:
                return abs(x) - radius
        else:
            # Equal dimensions = circle
            return math.sqrt(x * x + y * y) - half_w

    @staticmethod
    def _point_to_roundrect(x: float, y: float, half_w: float, half_h: float,
                            corner_radius: float) -> float:
        """Distance from point to rounded rectangle."""
        # Clamp corner radius to valid range
        corner_radius = min(corner_radius, half_w, half_h)

        if corner_radius <= 0:
            # No rounding, treat as regular rectangle
            return GeometryChecker._point_to_rect(x, y, half_w, half_h)

        # Inner rectangle dimensions (excluding corners)
        inner_half_w = half_w - corner_radius
        inner_half_h = half_h - corner_radius

        # Check which zone the point is in
        if abs(x) <= inner_half_w:
            # In the horizontal strip (top, middle, or bottom)
            return abs(y) - half_h
        elif abs(y) <= inner_half_h:
            # In the vertical strip (left or right)
            return abs(x) - half_w
        else:
            # In a corner region - distance to corner arc
            corner_x = inner_half_w if x > 0 else -inner_half_w
            corner_y = inner_half_h if y > 0 else -inner_half_h
            return math.sqrt((x - corner_x) ** 2 + (y - corner_y) ** 2) - corner_radius

    @staticmethod
    def point_to_trace_distance(px: float, py: float, trace: TraceInfo) -> float:
        """
        Distance from point to trace edge.

        Trace is a capsule (line segment with rounded ends).
        """
        half_width = trace.width / 2
        centerline_dist = GeometryChecker._point_to_segment(
            px, py,
            trace.start_x, trace.start_y,
            trace.end_x, trace.end_y
        )
        return centerline_dist - half_width

    @staticmethod
    def point_to_via_distance(px: float, py: float, via: ViaInfo) -> float:
        """Distance from point to via edge (via is a circle)."""
        radius = via.size / 2
        dist = math.sqrt((px - via.x) ** 2 + (py - via.y) ** 2)
        return dist - radius

    @staticmethod
    def _point_to_segment(px: float, py: float,
                          x1: float, y1: float,
                          x2: float, y2: float) -> float:
        """Calculate shortest distance from point to line segment."""
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq < 0.000001:
            # Degenerate segment (start == end)
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        # Project point onto line: t = (P-A) dot (B-A) / |B-A|^2
        t = ((px - x1) * dx + (py - y1) * dy) / length_sq
        t = max(0.0, min(1.0, t))  # Clamp to segment

        # Closest point on segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)


def segment_segment_intersection(
    p1x: float, p1y: float,
    p2x: float, p2y: float,
    p3x: float, p3y: float,
    p4x: float, p4y: float,
    epsilon: float = 1e-10
) -> Optional[tuple[float, float]]:
    """
    Find intersection point of two line segments.

    Args:
        p1x, p1y, p2x, p2y: First segment endpoints
        p3x, p3y, p4x, p4y: Second segment endpoints
        epsilon: Tolerance for parallel/coincident detection

    Returns:
        (x, y) intersection point or None if segments don't intersect
    """
    # Direction vectors
    d1x = p2x - p1x
    d1y = p2y - p1y
    d2x = p4x - p3x
    d2y = p4y - p3y
    d3x = p3x - p1x
    d3y = p3y - p1y

    # Cross product of directions
    cross = d1x * d2y - d1y * d2x

    # Check if segments are parallel
    if abs(cross) < epsilon:
        return None

    # Calculate intersection parameters
    t = (d3x * d2y - d3y * d2x) / cross
    u = (d3x * d1y - d3y * d1x) / cross

    # Check if intersection is within both segments
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (p1x + d1x * t, p1y + d1y * t)

    return None


def segment_polyline_intersections(
    p1x: float, p1y: float,
    p2x: float, p2y: float,
    polyline: list[tuple[float, float]],
    closed: bool = True
) -> list[tuple[float, float, int, float]]:
    """
    Find all intersection points between a line segment and a polyline.

    Args:
        p1x, p1y, p2x, p2y: Query segment endpoints
        polyline: List of (x, y) vertices
        closed: If True, connect last vertex to first

    Returns:
        List of (x, y, edge_index, t_along_query) sorted by distance from p1.
        edge_index is the polyline edge that was intersected.
        t_along_query is the parameter [0,1] along the query segment.
    """
    intersections = []
    n = len(polyline)

    if n < 2:
        return intersections

    num_edges = n if closed else n - 1

    for i in range(num_edges):
        e1 = polyline[i]
        e2 = polyline[(i + 1) % n]

        pt = segment_segment_intersection(
            p1x, p1y, p2x, p2y,
            e1[0], e1[1], e2[0], e2[1]
        )
        if pt is not None:
            # Calculate t along query segment
            dx = p2x - p1x
            dy = p2y - p1y
            length_sq = dx * dx + dy * dy
            if length_sq > 1e-10:
                t = ((pt[0] - p1x) * dx + (pt[1] - p1y) * dy) / length_sq
            else:
                t = 0.0
            intersections.append((pt[0], pt[1], i, t))

    # Sort by t (distance along query segment)
    intersections.sort(key=lambda x: x[3])
    return intersections


def line_side(
    px: float, py: float,
    l1x: float, l1y: float,
    l2x: float, l2y: float
) -> float:
    """
    Determine which side of a line a point is on.

    Returns:
        > 0 if point is to the left of line (l1 -> l2)
        < 0 if point is to the right
        = 0 if point is on the line
    """
    return (l2x - l1x) * (py - l1y) - (l2y - l1y) * (px - l1x)


def segments_intersect(
    p1x: float, p1y: float,
    p2x: float, p2y: float,
    p3x: float, p3y: float,
    p4x: float, p4y: float
) -> bool:
    """
    Check if two line segments intersect (boolean only, faster).

    Args:
        p1x, p1y, p2x, p2y: First segment endpoints
        p3x, p3y, p4x, p4y: Second segment endpoints

    Returns:
        True if segments intersect
    """
    # Check bounding box overlap first (fast rejection)
    if (max(p1x, p2x) < min(p3x, p4x) or max(p3x, p4x) < min(p1x, p2x) or
        max(p1y, p2y) < min(p3y, p4y) or max(p3y, p4y) < min(p1y, p2y)):
        return False

    # Cross product test
    d1 = line_side(p3x, p3y, p1x, p1y, p2x, p2y)
    d2 = line_side(p4x, p4y, p1x, p1y, p2x, p2y)
    d3 = line_side(p1x, p1y, p3x, p3y, p4x, p4y)
    d4 = line_side(p2x, p2y, p3x, p3y, p4x, p4y)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # Check for collinear cases
    if d1 == 0 and on_segment(p3x, p3y, p1x, p1y, p2x, p2y):
        return True
    if d2 == 0 and on_segment(p4x, p4y, p1x, p1y, p2x, p2y):
        return True
    if d3 == 0 and on_segment(p1x, p1y, p3x, p3y, p4x, p4y):
        return True
    if d4 == 0 and on_segment(p2x, p2y, p3x, p3y, p4x, p4y):
        return True

    return False


def on_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float
) -> bool:
    """Check if point p lies on segment ab (assuming collinearity)."""
    return (min(ax, bx) <= px <= max(ax, bx) and
            min(ay, by) <= py <= max(ay, by))


def closest_point_on_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float
) -> tuple[float, float, float]:
    """
    Find closest point on segment ab to point p.

    Returns:
        (x, y, t) where (x, y) is the closest point and t is parameter [0, 1]
    """
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy

    if length_sq < 1e-10:
        return (ax, ay, 0.0)

    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))

    return (ax + dx * t, ay + dy * t, t)
