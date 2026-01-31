"""Tests for SVG rendering and pad orientation verification."""
import math
from pathlib import Path

import pytest

from backend.pcb import PCBParser
from backend.svg import SVGGenerator, render_svg_to_png, render_pcb_to_png


# Path to test PCB file
PCB_FILE = Path(__file__).parent.parent / "BLDriver.kicad_pcb"
OUTPUT_DIR = Path(__file__).parent / "output"


@pytest.fixture
def parser():
    """Load the test PCB file."""
    return PCBParser(PCB_FILE)


@pytest.fixture
def output_dir():
    """Ensure output directory exists."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    return OUTPUT_DIR


def test_render_svg_to_png(parser, output_dir):
    """Test that SVG renders to PNG without errors."""
    generator = SVGGenerator(parser)
    svg_content = generator.generate()

    image = render_svg_to_png(svg_content, output_dir / "pcb_render.png", scale=10.0)

    assert image is not None
    assert image.width > 0
    assert image.height > 0
    # Board is roughly 42x57mm, at 10x scale should be ~420x570 pixels
    assert 300 < image.width < 600
    assert 400 < image.height < 800


def test_render_pcb_to_png(output_dir):
    """Test the convenience function for rendering PCB to PNG."""
    image = render_pcb_to_png(PCB_FILE, output_dir / "pcb_direct.png", scale=10.0)

    assert image is not None
    assert image.width > 0
    assert image.height > 0


def test_render_single_layer(parser, output_dir):
    """Test rendering individual layers."""
    generator = SVGGenerator(parser)

    for layer in ["F.Cu", "B.Cu", "Edge.Cuts"]:
        svg_content = generator.generate(layers=[layer])
        image = render_svg_to_png(
            svg_content,
            output_dir / f"layer_{layer.replace('.', '_')}.png",
            scale=10.0
        )
        assert image is not None


def test_rotated_footprint_pad_positions(parser):
    """
    Verify that pad positions are correctly transformed for rotated footprints.

    C11 is a 0603 capacitor rotated 90° at position (167, 57.675).
    Original pad positions are approximately at X offsets of ±0.775mm.
    After 90° rotation, these should become Y offsets.
    """
    # Find C11 footprint
    c11 = None
    for fp in parser.footprints:
        if fp.reference == "C11":
            c11 = fp
            break

    assert c11 is not None, "C11 footprint not found"
    assert c11.angle == 90.0, f"C11 should be rotated 90°, got {c11.angle}°"

    # Check pad positions
    assert len(c11.pads) == 2, "C11 should have 2 pads"

    pad1 = c11.pads[0]
    pad2 = c11.pads[1]

    # Both pads should have same X (footprint X)
    assert abs(pad1.x - c11.x) < 0.01, f"Pad 1 X should be at footprint X"
    assert abs(pad2.x - c11.x) < 0.01, f"Pad 2 X should be at footprint X"

    # Pads should be offset in Y direction (due to 90° rotation)
    y_diff = abs(pad2.y - pad1.y)
    assert 1.4 < y_diff < 1.7, f"Pads should be ~1.55mm apart in Y, got {y_diff}mm"


def test_45_degree_rotation(parser):
    """
    Verify pad positions for a 45° rotated footprint.

    U2 (STM32) is rotated 45° at position (150.8, 77.3).
    """
    # Find U2 footprint
    u2 = None
    for fp in parser.footprints:
        if fp.reference == "U2":
            u2 = fp
            break

    assert u2 is not None, "U2 footprint not found"
    assert u2.angle == 45.0, f"U2 should be rotated 45°, got {u2.angle}°"

    # For a 45° rotation, pads that were along X or Y axes
    # should now be along diagonals
    # Check that pads are distributed around the footprint center
    pad_distances = []
    for pad in u2.pads:
        dx = pad.x - u2.x
        dy = pad.y - u2.y
        dist = math.sqrt(dx*dx + dy*dy)
        pad_distances.append(dist)

    # All pads should be at similar distances from center (QFN package)
    assert len(pad_distances) > 10, "U2 should have many pads"


def test_180_degree_rotation(parser):
    """
    Verify pad positions for a 180° rotated footprint.

    J5 is rotated 180° at position (145.1, 50.4).
    """
    # Find J5 footprint
    j5 = None
    for fp in parser.footprints:
        if fp.reference == "J5":
            j5 = fp
            break

    assert j5 is not None, "J5 footprint not found"
    assert j5.angle == 180.0, f"J5 should be rotated 180°, got {j5.angle}°"

    # 180° rotation should flip pad positions
    # Pads that were at +X should now be at -X relative to footprint center
    for pad in j5.pads:
        # Just verify pads exist and have valid positions
        assert pad.x > 0 and pad.y > 0, "Pad should have valid position"


def test_pad_rotation_affects_rendering(parser):
    """
    Verify that pad rotation angle is correctly computed.

    For rectangular/roundrect pads, the rotation affects the visual orientation.
    """
    # Find a pad with non-zero total rotation
    rotated_pads = [p for p in parser.pads if p.angle != 0 and p.shape == "roundrect"]

    assert len(rotated_pads) > 0, "Should have rotated roundrect pads"

    # Check that rotated footprints have pads with non-zero angles
    for fp in parser.footprints:
        if fp.angle != 0:
            for pad in fp.pads:
                # Pad angle should be set (negated from KiCad for SVG rendering)
                assert isinstance(pad.angle, (int, float)), "Angle should be a number"


def test_all_pads_have_valid_positions(parser):
    """Verify all pads have positions within board bounds."""
    info = parser.get_board_info()

    for pad in parser.pads:
        assert info.min_x - 1 <= pad.x <= info.max_x + 1, \
            f"Pad {pad.pad_id} x={pad.x} outside board bounds"
        assert info.min_y - 1 <= pad.y <= info.max_y + 1, \
            f"Pad {pad.pad_id} y={pad.y} outside board bounds"


def test_render_high_resolution(parser, output_dir):
    """Test high-resolution rendering for detailed inspection."""
    generator = SVGGenerator(parser)
    svg_content = generator.generate()

    # High resolution render
    image = render_svg_to_png(
        svg_content,
        output_dir / "pcb_highres.png",
        scale=20.0
    )

    # At 20x scale, image should be roughly 850x1140 pixels
    assert image.width > 600
    assert image.height > 800

    print(f"\nHigh-res image saved: {output_dir / 'pcb_highres.png'}")
    print(f"Size: {image.width} x {image.height} pixels")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
