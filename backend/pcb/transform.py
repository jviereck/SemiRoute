"""Coordinate transformation utilities."""
import math


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """
    Rotate a point around the origin by the given angle.

    Args:
        x: X coordinate
        y: Y coordinate
        angle_deg: Rotation angle in degrees (counterclockwise positive)

    Returns:
        Tuple of (rotated_x, rotated_y)
    """
    if angle_deg == 0:
        return x, y

    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    rotated_x = x * cos_a - y * sin_a
    rotated_y = x * sin_a + y * cos_a

    return rotated_x, rotated_y


def transform_pad_position(
    pad_x: float,
    pad_y: float,
    pad_angle: float,
    fp_x: float,
    fp_y: float,
    fp_angle: float
) -> tuple[float, float, float]:
    """
    Transform pad position from footprint-relative to board-absolute coordinates.

    Args:
        pad_x: Pad X offset from footprint origin
        pad_y: Pad Y offset from footprint origin
        pad_angle: Pad visual angle (already absolute in KiCad 9 PCB files)
        fp_x: Footprint X position on board
        fp_y: Footprint Y position on board
        fp_angle: Footprint rotation on board (degrees)

    Returns:
        Tuple of (absolute_x, absolute_y, visual_angle)
    """
    # Rotate pad offset by negative footprint angle (KiCad uses opposite rotation direction)
    rotated_x, rotated_y = rotate_point(pad_x, pad_y, -fp_angle)

    # Translate to footprint position
    absolute_x = fp_x + rotated_x
    absolute_y = fp_y + rotated_y

    # In KiCad 9 PCB files, pad angles are already absolute (include footprint rotation)
    # Negate to match SVG coordinate system
    visual_angle = -pad_angle if pad_angle is not None else 0

    return absolute_x, absolute_y, visual_angle
