"""Test for route crossing U2 pad 9 issue."""
import math
import pytest
from pathlib import Path

from backend.pcb import PCBParser
from backend.routing import TraceRouter, ObstacleMap

PCB_FILE = Path(__file__).parent.parent / "BLDriver.kicad_pcb"


def point_to_rotated_rect_distance(
    px: float, py: float,
    rect_cx: float, rect_cy: float,
    rect_width: float, rect_height: float,
    rect_angle_deg: float
) -> float:
    """
    Calculate the minimum distance from a point to the edge of a rotated rectangle.

    Returns negative if point is inside the rectangle, positive if outside.
    """
    # Translate point to rectangle's local coordinate system
    dx = px - rect_cx
    dy = py - rect_cy

    # Rotate point to align with rectangle axes (rotate by -angle)
    angle_rad = math.radians(-rect_angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    local_x = dx * cos_a - dy * sin_a
    local_y = dx * sin_a + dy * cos_a

    # Half dimensions
    half_w = rect_width / 2
    half_h = rect_height / 2

    # Find distance to rectangle in local coordinates
    # For a point, find the closest point on the rectangle boundary
    if abs(local_x) <= half_w and abs(local_y) <= half_h:
        # Point is inside - return negative distance to nearest edge
        dist_to_x_edge = half_w - abs(local_x)
        dist_to_y_edge = half_h - abs(local_y)
        return -min(dist_to_x_edge, dist_to_y_edge)

    # Point is outside - find closest point on boundary
    closest_x = max(-half_w, min(half_w, local_x))
    closest_y = max(-half_h, min(half_h, local_y))

    return math.sqrt((local_x - closest_x)**2 + (local_y - closest_y)**2)


def segment_to_rotated_rect_min_distance(
    x1: float, y1: float, x2: float, y2: float,
    rect_cx: float, rect_cy: float,
    rect_width: float, rect_height: float,
    rect_angle_deg: float
) -> float:
    """
    Calculate minimum distance from a line segment to a rotated rectangle edge.

    Samples along the segment for a conservative estimate.
    """
    # Sample the segment
    length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
    if length < 0.001:
        return point_to_rotated_rect_distance(
            x1, y1, rect_cx, rect_cy, rect_width, rect_height, rect_angle_deg
        )

    num_samples = max(10, int(length / 0.01))  # Sample every 0.01mm
    min_dist = float('inf')

    for i in range(num_samples + 1):
        t = i / num_samples
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        dist = point_to_rotated_rect_distance(
            px, py, rect_cx, rect_cy, rect_width, rect_height, rect_angle_deg
        )
        min_dist = min(min_dist, dist)

    return min_dist


def test_route_c5_to_u2_pad8_avoids_u2_pad9():
    """Test that route from C5 pad 1 to U2 pad 8 avoids U2 pad 9."""
    parser = PCBParser(PCB_FILE)
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=True)

    # Find the pads
    c5_pad1 = None
    u2_pad8 = None
    u2_pad9 = None

    for pad in parser.pads:
        if pad.footprint_ref == 'C5' and pad.name == '1':
            c5_pad1 = pad
        elif pad.footprint_ref == 'U2' and pad.name == '8':
            u2_pad8 = pad
        elif pad.footprint_ref == 'U2' and pad.name == '9':
            u2_pad9 = pad

    assert c5_pad1 is not None, "C5 pad 1 not found"
    assert u2_pad8 is not None, "U2 pad 8 not found"
    assert u2_pad9 is not None, "U2 pad 9 not found"

    print(f"\nC5 pad 1: ({c5_pad1.x}, {c5_pad1.y}), net={c5_pad1.net_id} ({parser.nets.get(c5_pad1.net_id)})")
    print(f"U2 pad 8: ({u2_pad8.x}, {u2_pad8.y}), net={u2_pad8.net_id} ({parser.nets.get(u2_pad8.net_id)})")
    print(f"U2 pad 9: ({u2_pad9.x}, {u2_pad9.y}), net={u2_pad9.net_id} ({parser.nets.get(u2_pad9.net_id)})")
    print(f"U2 pad 9 size: {u2_pad9.width} x {u2_pad9.height}, angle={u2_pad9.angle}")

    # Route from C5 to U2 pad 8 (both GND)
    path = router.route(
        c5_pad1.x, c5_pad1.y,
        u2_pad8.x, u2_pad8.y,
        'F.Cu', 0.25,
        net_id=c5_pad1.net_id  # GND
    )

    assert path, "Route should be found"
    print(f"\nRoute has {len(path)} waypoints")

    trace_radius = 0.125  # Half of 0.25mm trace
    clearance = 0.2

    # Check clearance using actual rotated rectangle geometry
    min_clearance = float('inf')
    violation_segment = None

    for i in range(len(path) - 1):
        x1, y1 = path[i]
        x2, y2 = path[i + 1]

        # Distance from segment to pad 9's actual geometry
        dist_to_pad_edge = segment_to_rotated_rect_min_distance(
            x1, y1, x2, y2,
            u2_pad9.x, u2_pad9.y,
            u2_pad9.width, u2_pad9.height,
            u2_pad9.angle
        )

        # Actual clearance = distance to pad edge - trace radius
        actual_clearance = dist_to_pad_edge - trace_radius

        if actual_clearance < min_clearance:
            min_clearance = actual_clearance
            violation_segment = (i, x1, y1, x2, y2, dist_to_pad_edge)

    print(f"\nMinimum clearance to U2 pad 9 (actual rotated geometry): {min_clearance:.4f}mm")
    print(f"Required clearance: {clearance:.4f}mm")

    if violation_segment:
        i, x1, y1, x2, y2, dist = violation_segment
        print(f"Closest segment {i}: ({x1:.3f},{y1:.3f}) to ({x2:.3f},{y2:.3f})")
        print(f"  Distance to pad edge: {dist:.4f}mm")

    # Check that minimum clearance is at least the required clearance
    # Allow small tolerance (0.01mm = 10um) for grid discretization effects
    # Grid-based routing can't perfectly match exact clearance requirements
    tolerance = 0.01  # 10 micrometers
    assert min_clearance >= clearance - tolerance, (
        f"Path violates clearance to U2 pad 9: {min_clearance:.4f}mm < {clearance - tolerance:.4f}mm required (with {tolerance}mm tolerance)"
    )
