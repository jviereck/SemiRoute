"""SVG element generators for PCB features."""
import math
from xml.etree.ElementTree import Element
from typing import Union

from backend.pcb.models import (
    GraphicArc, GraphicLine, GraphicRect, GraphicCircle, GraphicPoly, PadInfo
)

from .styles import (
    DEFAULT_STROKE_WIDTH, EDGE_CUTS_STROKE_WIDTH, GRAPHICS_OPACITY,
    LAYER_COLORS, PAD_OPACITY
)


def _circle_from_three_points(
    x1: float, y1: float,
    x2: float, y2: float,
    x3: float, y3: float
) -> tuple[float, float, float] | None:
    """
    Calculate circle center and radius from three points.

    Returns (center_x, center_y, radius) or None if points are collinear.
    """
    # Using the circumcircle formula
    ax, ay = x1, y1
    bx, by = x2, y2
    cx, cy = x3, y3

    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-10:
        return None  # Points are collinear

    ux = ((ax*ax + ay*ay) * (by - cy) + (bx*bx + by*by) * (cy - ay) + (cx*cx + cy*cy) * (ay - by)) / d
    uy = ((ax*ax + ay*ay) * (cx - bx) + (bx*bx + by*by) * (ax - cx) + (cx*cx + cy*cy) * (bx - ax)) / d

    radius = math.sqrt((ax - ux)**2 + (ay - uy)**2)
    return ux, uy, radius


def _arc_sweep_flag(
    cx: float, cy: float,
    x1: float, y1: float,
    x2: float, y2: float,
    xm: float, ym: float
) -> int:
    """
    Determine SVG arc sweep flag based on midpoint position.

    Returns 1 for clockwise, 0 for counter-clockwise.
    """
    # Calculate angles from center to start, mid, and end
    angle_start = math.atan2(y1 - cy, x1 - cx)
    angle_mid = math.atan2(ym - cy, xm - cx)
    angle_end = math.atan2(y2 - cy, x2 - cx)

    # Normalize angles to [0, 2*pi]
    def normalize(a):
        while a < 0:
            a += 2 * math.pi
        while a >= 2 * math.pi:
            a -= 2 * math.pi
        return a

    angle_start = normalize(angle_start)
    angle_mid = normalize(angle_mid)
    angle_end = normalize(angle_end)

    # Check if going start -> mid -> end is clockwise or counter-clockwise
    # by checking if mid is between start and end going clockwise
    if angle_start <= angle_end:
        mid_between_cw = not (angle_start <= angle_mid <= angle_end)
    else:
        mid_between_cw = (angle_end <= angle_mid <= angle_start)

    # Invert because SVG Y-axis is flipped relative to KiCad
    return 0 if mid_between_cw else 1

GraphicItem = Union[GraphicLine, GraphicArc, GraphicRect, GraphicCircle, GraphicPoly]


def _get_rotated_rect_dimensions(width: float, height: float, angle: float) -> tuple[float, float]:
    """
    Get effective width and height for a rotated rectangle.
    For 90° multiples, swap dimensions. For other angles, compute bounding box.
    """
    # Normalize angle to 0-360
    angle = angle % 360
    if angle < 0:
        angle += 360

    # For 90° or 270°, swap width and height
    if abs(angle - 90) < 0.1 or abs(angle - 270) < 0.1:
        return height, width
    return width, height


def _rotate_point_around(px: float, py: float, cx: float, cy: float, angle_deg: float) -> tuple[float, float]:
    """Rotate point (px, py) around center (cx, cy) by angle in degrees."""
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Translate to origin
    dx = px - cx
    dy = py - cy

    # Rotate
    rx = dx * cos_a - dy * sin_a
    ry = dx * sin_a + dy * cos_a

    # Translate back
    return cx + rx, cy + ry


def create_pad_element(pad: PadInfo, layer: str) -> Element | None:
    """
    Create an SVG element for a pad.

    Args:
        pad: Pad information
        layer: Layer to render on

    Returns:
        SVG element or None if pad not on this layer
    """
    if layer not in pad.layers:
        return None

    color = LAYER_COLORS.get(layer, "#888888")

    # Common attributes
    attrs = {
        "id": f"pad-{pad.pad_id}",
        "data-net": str(pad.net_id),
        "data-net-name": pad.net_name,
        "data-footprint": pad.footprint_ref,
        "data-pad": pad.name,
        "data-layer": layer,
        "data-x": f"{pad.x:.4f}",
        "data-y": f"{pad.y:.4f}",
        "fill": color,
        "fill-opacity": str(PAD_OPACITY),
        "class": "pad",
    }

    # Create element based on shape
    if pad.shape == "circle":
        # Circle: use radius as half of smaller dimension
        radius = min(pad.width, pad.height) / 2
        elem = Element("circle", {
            **attrs,
            "cx": f"{pad.x:.4f}",
            "cy": f"{pad.y:.4f}",
            "r": f"{radius:.4f}",
        })

    elif pad.shape == "oval":
        # Oval: use polygon with rotated corners for proper click detection
        if pad.angle != 0:
            # Create ellipse approximation as polygon
            rx, ry = pad.width / 2, pad.height / 2
            points = []
            for i in range(16):  # 16-point approximation
                t = 2 * math.pi * i / 16
                px = pad.x + rx * math.cos(t)
                py = pad.y + ry * math.sin(t)
                rpx, rpy = _rotate_point_around(px, py, pad.x, pad.y, pad.angle)
                points.append(f"{rpx:.4f},{rpy:.4f}")
            elem = Element("polygon", {
                **attrs,
                "points": " ".join(points),
            })
        else:
            elem = Element("ellipse", {
                **attrs,
                "cx": f"{pad.x:.4f}",
                "cy": f"{pad.y:.4f}",
                "rx": f"{pad.width/2:.4f}",
                "ry": f"{pad.height/2:.4f}",
            })

    elif pad.shape == "roundrect":
        corner_radius = pad.roundrect_ratio * min(pad.width, pad.height) / 2
        if pad.angle != 0:
            # Use polygon for rotated pads - negate angle for SVG coordinate system
            w2, h2 = pad.width / 2, pad.height / 2
            r = min(corner_radius, w2, h2)
            n_corner = 4
            points = []
            # Top-right corner
            for i in range(n_corner + 1):
                t = -math.pi/2 + (math.pi/2) * i / n_corner
                px = pad.x + w2 - r + r * math.cos(t)
                py = pad.y - h2 + r + r * math.sin(t)
                rpx, rpy = _rotate_point_around(px, py, pad.x, pad.y, pad.angle)
                points.append(f"{rpx:.4f},{rpy:.4f}")
            # Bottom-right corner
            for i in range(1, n_corner + 1):
                t = 0 + (math.pi/2) * i / n_corner
                px = pad.x + w2 - r + r * math.cos(t)
                py = pad.y + h2 - r + r * math.sin(t)
                rpx, rpy = _rotate_point_around(px, py, pad.x, pad.y, pad.angle)
                points.append(f"{rpx:.4f},{rpy:.4f}")
            # Bottom-left corner
            for i in range(1, n_corner + 1):
                t = math.pi/2 + (math.pi/2) * i / n_corner
                px = pad.x - w2 + r + r * math.cos(t)
                py = pad.y + h2 - r + r * math.sin(t)
                rpx, rpy = _rotate_point_around(px, py, pad.x, pad.y, pad.angle)
                points.append(f"{rpx:.4f},{rpy:.4f}")
            # Top-left corner
            for i in range(1, n_corner + 1):
                t = math.pi + (math.pi/2) * i / n_corner
                px = pad.x - w2 + r + r * math.cos(t)
                py = pad.y - h2 + r + r * math.sin(t)
                rpx, rpy = _rotate_point_around(px, py, pad.x, pad.y, pad.angle)
                points.append(f"{rpx:.4f},{rpy:.4f}")
            elem = Element("polygon", {**attrs, "points": " ".join(points)})
        else:
            elem = Element("rect", {
                **attrs,
                "x": f"{pad.x - pad.width/2:.4f}",
                "y": f"{pad.y - pad.height/2:.4f}",
                "width": f"{pad.width:.4f}",
                "height": f"{pad.height:.4f}",
                "rx": f"{corner_radius:.4f}",
                "ry": f"{corner_radius:.4f}",
            })

    else:  # rect or default
        if pad.angle != 0:
            # Use polygon for rotated rects - negate angle for SVG coordinate system
            w2, h2 = pad.width / 2, pad.height / 2
            corners = [
                (pad.x - w2, pad.y - h2),
                (pad.x + w2, pad.y - h2),
                (pad.x + w2, pad.y + h2),
                (pad.x - w2, pad.y + h2),
            ]
            rotated = [_rotate_point_around(px, py, pad.x, pad.y, pad.angle) for px, py in corners]
            elem = Element("polygon", {**attrs, "points": " ".join(f"{x:.4f},{y:.4f}" for x, y in rotated)})
        else:
            elem = Element("rect", {
                **attrs,
                "x": f"{pad.x - pad.width/2:.4f}",
                "y": f"{pad.y - pad.height/2:.4f}",
                "width": f"{pad.width:.4f}",
                "height": f"{pad.height:.4f}",
            })

    return elem


def create_graphic_element(item: GraphicItem) -> Element:
    """Create an SVG element for a graphic item."""
    layer = item.layer
    color = LAYER_COLORS.get(layer, "#888888")
    stroke_width = item.width if item.width > 0 else DEFAULT_STROKE_WIDTH

    # Use thicker stroke for edge cuts
    if layer == "Edge.Cuts":
        stroke_width = max(stroke_width, EDGE_CUTS_STROKE_WIDTH)

    if isinstance(item, GraphicLine):
        return Element("line", {
            "x1": f"{item.start_x:.4f}",
            "y1": f"{item.start_y:.4f}",
            "x2": f"{item.end_x:.4f}",
            "y2": f"{item.end_y:.4f}",
            "stroke": color,
            "stroke-width": f"{stroke_width:.4f}",
            "stroke-linecap": "round",
            "stroke-opacity": str(GRAPHICS_OPACITY),
        })

    elif isinstance(item, GraphicArc):
        # Calculate circle from start, mid, end points
        circle = _circle_from_three_points(
            item.start_x, item.start_y,
            item.mid_x, item.mid_y,
            item.end_x, item.end_y
        )

        if circle:
            cx, cy, radius = circle
            # Determine arc direction based on midpoint
            sweep = _arc_sweep_flag(
                cx, cy,
                item.start_x, item.start_y,
                item.end_x, item.end_y,
                item.mid_x, item.mid_y
            )
            # For small arcs, large-arc-flag is 0
            large_arc = 0
            d = (
                f"M {item.start_x:.4f} {item.start_y:.4f} "
                f"A {radius:.4f} {radius:.4f} 0 {large_arc} {sweep} "
                f"{item.end_x:.4f} {item.end_y:.4f}"
            )
        else:
            # Fallback to line if points are collinear
            d = f"M {item.start_x:.4f} {item.start_y:.4f} L {item.end_x:.4f} {item.end_y:.4f}"

        return Element("path", {
            "d": d,
            "stroke": color,
            "stroke-width": f"{stroke_width:.4f}",
            "stroke-linecap": "round",
            "stroke-opacity": str(GRAPHICS_OPACITY),
            "fill": "none",
        })

    elif isinstance(item, GraphicRect):
        x1, y1 = item.start_x, item.start_y
        x2, y2 = item.end_x, item.end_y
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return Element("rect", {
            "x": f"{x:.4f}",
            "y": f"{y:.4f}",
            "width": f"{w:.4f}",
            "height": f"{h:.4f}",
            "stroke": color,
            "stroke-width": f"{stroke_width:.4f}",
            "stroke-opacity": str(GRAPHICS_OPACITY),
            "fill": color if item.fill else "none",
            "fill-opacity": str(GRAPHICS_OPACITY) if item.fill else "0",
        })

    elif isinstance(item, GraphicCircle):
        return Element("circle", {
            "cx": f"{item.center_x:.4f}",
            "cy": f"{item.center_y:.4f}",
            "r": f"{item.radius:.4f}",
            "stroke": color,
            "stroke-width": f"{stroke_width:.4f}",
            "stroke-opacity": str(GRAPHICS_OPACITY),
            "fill": color if item.fill else "none",
            "fill-opacity": str(GRAPHICS_OPACITY) if item.fill else "0",
        })

    elif isinstance(item, GraphicPoly):
        if not item.points:
            return Element("g")
        points_str = " ".join(f"{x:.4f},{y:.4f}" for x, y in item.points)
        return Element("polygon", {
            "points": points_str,
            "stroke": color,
            "stroke-width": f"{stroke_width:.4f}",
            "stroke-linejoin": "round",
            "stroke-opacity": str(GRAPHICS_OPACITY),
            "fill": color if item.fill else "none",
            "fill-opacity": str(GRAPHICS_OPACITY) if item.fill else "0",
        })

    # Fallback
    return Element("g")


def create_drill_hole(pad: PadInfo) -> Element | None:
    """Create an SVG element for a drill hole."""
    if not pad.drill:
        return None

    return Element("circle", {
        "cx": f"{pad.x:.4f}",
        "cy": f"{pad.y:.4f}",
        "r": f"{pad.drill/2:.4f}",
        "fill": "#1a1a1a",  # Background color
        "class": "drill-hole",
    })
