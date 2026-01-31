"""Tests for the PCB parser."""
import pytest
from pathlib import Path

from backend.pcb import PCBParser, BoardInfo


# Path to test PCB file
PCB_FILE = Path(__file__).parent.parent / "BLDriver.kicad_pcb"


@pytest.fixture
def parser():
    """Load the test PCB file."""
    return PCBParser(PCB_FILE)


def test_parser_loads_file(parser):
    """Test that the parser loads the file without errors."""
    assert parser.board is not None


def test_parser_extracts_footprints(parser):
    """Test that footprints are extracted."""
    assert len(parser.footprints) > 0
    # Plan mentions 38 footprints
    assert len(parser.footprints) >= 30


def test_parser_extracts_pads(parser):
    """Test that pads are extracted."""
    assert len(parser.pads) > 0
    # Plan mentions 408 pads
    assert len(parser.pads) >= 400


def test_parser_extracts_nets(parser):
    """Test that nets are extracted."""
    assert len(parser.nets) > 0
    # Plan mentions ~90 nets
    assert len(parser.nets) >= 80


def test_parser_extracts_edge_cuts(parser):
    """Test that edge cuts are extracted."""
    assert len(parser.edge_cuts) > 0


def test_board_info(parser):
    """Test board info extraction."""
    info = parser.get_board_info()

    assert isinstance(info, BoardInfo)
    assert info.width > 0
    assert info.height > 0
    assert info.footprint_count > 0
    assert info.pad_count > 0
    assert info.net_count > 0


def test_pad_positions_are_absolute(parser):
    """Test that pad positions are absolute (transformed)."""
    # All pads should have positive coordinates in reasonable range
    for pad in parser.pads:
        # KiCad boards typically have positive coordinates
        # This board appears to be around 130-175mm X, 50-110mm Y
        assert 100 < pad.x < 200, f"Pad {pad.pad_id} x={pad.x} out of expected range"
        assert 40 < pad.y < 120, f"Pad {pad.pad_id} y={pad.y} out of expected range"


def test_get_pads_by_net(parser):
    """Test getting pads by net."""
    # GND should have many pads
    gnd_pads = parser.get_pads_by_net(2)  # GND is net 2
    assert len(gnd_pads) > 10, "GND net should have many pads"


def test_get_pads_by_layer(parser):
    """Test getting pads by layer."""
    front_pads = parser.get_pads_by_layer("F.Cu")
    back_pads = parser.get_pads_by_layer("B.Cu")

    assert len(front_pads) > 0
    # SMD components are mostly on front
    assert len(front_pads) > len(back_pads)


def test_known_nets_exist(parser):
    """Test that known nets from the plan exist."""
    net_names = list(parser.nets.values())

    assert "VM" in net_names
    assert "GND" in net_names
    assert "3V3" in net_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
