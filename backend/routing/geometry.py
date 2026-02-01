"""Accurate geometry calculations for PCB elements."""
import math
from typing import Union

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
