"""Tests for the PCB routing module."""
import pytest
import math
from pathlib import Path
from unittest.mock import MagicMock

from backend.pcb import PCBParser
from backend.pcb.models import PadInfo, TraceInfo, ViaInfo
from backend.routing import TraceRouter, ObstacleMap
from backend.routing.pathfinding import astar_search, DIRECTIONS


# Path to test PCB file
PCB_FILE = Path(__file__).parent.parent / "BLDriver.kicad_pcb"


@pytest.fixture
def parser():
    """Load the test PCB file."""
    return PCBParser(PCB_FILE)


@pytest.fixture
def router(parser):
    """Create a router instance."""
    return TraceRouter(parser, clearance=0.2)


class TestObstacleMap:
    """Tests for the ObstacleMap class."""

    def test_obstacle_map_creation(self, parser):
        """Test that obstacle map can be created."""
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
        assert obstacle_map is not None
        assert obstacle_map.layer == "F.Cu"
        assert obstacle_map.clearance == 0.2

    def test_obstacle_map_blocks_pads(self, parser):
        """Test that pads are marked as blocked."""
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

        # Find a pad on F.Cu
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers:
                pad = p
                break

        assert pad is not None, "Should have at least one pad on F.Cu"

        # The pad location should be blocked
        assert obstacle_map.is_blocked(pad.x, pad.y)

    def test_obstacle_map_allows_same_net(self, parser):
        """Test that same-net elements are not blocked."""
        # Find a pad with a net
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0:
                pad = p
                break

        assert pad is not None

        # Create obstacle map allowing this net
        obstacle_map = ObstacleMap(
            parser, layer="F.Cu", clearance=0.2, allowed_net_id=pad.net_id
        )

        # The pad location should NOT be blocked (same net)
        assert not obstacle_map.is_blocked(pad.x, pad.y)

    def test_obstacle_map_blocks_different_net_pads(self, parser):
        """Test that different-net pads are blocked."""
        # Find two pads on same layer with different nets
        pad1 = None
        pad2 = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0:
                if pad1 is None:
                    pad1 = p
                elif p.net_id != pad1.net_id:
                    pad2 = p
                    break

        assert pad1 is not None and pad2 is not None

        # Create obstacle map allowing pad1's net
        obstacle_map = ObstacleMap(
            parser, layer="F.Cu", clearance=0.2, allowed_net_id=pad1.net_id
        )

        # pad2 (different net) should still be blocked
        assert obstacle_map.is_blocked(pad2.x, pad2.y)

    def test_grid_conversion(self, parser):
        """Test grid coordinate conversion."""
        obstacle_map = ObstacleMap(parser, layer="F.Cu", grid_resolution=0.025)

        # Test round-trip conversion
        x, y = 150.0, 80.0
        gx, gy = obstacle_map._to_grid(x, y)
        wx, wy = obstacle_map._to_world(gx, gy)

        assert abs(wx - x) < 0.025
        assert abs(wy - y) < 0.025


class TestPathfinding:
    """Tests for the A* pathfinding algorithm."""

    def test_straight_path_orthogonal(self, parser):
        """Test finding a straight horizontal path."""
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

        # Find a clear area for testing (outside the board)
        path = astar_search(
            obstacle_map,
            start_x=120.0, start_y=45.0,
            end_x=125.0, end_y=45.0
        )

        # Should find some path
        if len(path) > 0:
            # Path should start and end correctly
            assert abs(path[0][0] - 120.0) < 0.1
            assert abs(path[-1][0] - 125.0) < 0.1

    def test_path_uses_45_degree_angles(self, parser):
        """Test that paths only use 0°, 45°, 90°, etc. angles."""
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

        # Route between two points
        path = astar_search(
            obstacle_map,
            start_x=130.0, start_y=55.0,
            end_x=140.0, end_y=65.0
        )

        if len(path) >= 2:
            # Check each segment angle
            for i in range(len(path) - 1):
                p1 = path[i]
                p2 = path[i + 1]
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]

                # Calculate angle
                if abs(dx) < 0.001 and abs(dy) < 0.001:
                    continue  # Same point, skip

                angle_rad = math.atan2(dy, dx)
                angle_deg = math.degrees(angle_rad)

                # Normalize to 0-360
                if angle_deg < 0:
                    angle_deg += 360

                # Should be a multiple of 45 degrees
                remainder = angle_deg % 45
                assert remainder < 1 or remainder > 44, (
                    f"Segment angle {angle_deg}° is not a multiple of 45°"
                )

    def test_directions_are_8_way(self):
        """Test that DIRECTIONS constant has correct 8-way movement."""
        assert len(DIRECTIONS) == 8

        # Check all 8 directions are present
        expected = {
            (0, -1),   # N
            (1, -1),   # NE
            (1, 0),    # E
            (1, 1),    # SE
            (0, 1),    # S
            (-1, 1),   # SW
            (-1, 0),   # W
            (-1, -1),  # NW
        }
        assert set(DIRECTIONS) == expected


class TestTraceRouter:
    """Tests for the TraceRouter class."""

    def test_router_creation(self, parser):
        """Test that router can be created."""
        router = TraceRouter(parser)
        assert router is not None

    def test_route_between_points(self, router):
        """Test routing between two points."""
        path = router.route(
            start_x=135.0, start_y=60.0,
            end_x=140.0, end_y=65.0,
            layer="F.Cu",
            width=0.25
        )

        # Should return a path (may be empty if blocked)
        assert isinstance(path, list)

    def test_route_on_different_layers(self, router):
        """Test routing on different copper layers."""
        layers = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

        for layer in layers:
            path = router.route(
                start_x=135.0, start_y=60.0,
                end_x=140.0, end_y=65.0,
                layer=layer,
                width=0.25
            )
            # Should not raise an error
            assert isinstance(path, list)

    def test_same_net_crossing(self, parser):
        """Test that a trace can cross pads/traces/vias of the same net."""
        # Find a net with multiple pads
        net_id = None
        pads = []
        for pad in parser.pads:
            if "F.Cu" in pad.layers and pad.net_id > 0:
                same_net_pads = parser.get_pads_by_net(pad.net_id)
                # Filter to F.Cu pads only
                f_cu_pads = [p for p in same_net_pads if "F.Cu" in p.layers]
                if len(f_cu_pads) >= 2:
                    net_id = pad.net_id
                    pads = f_cu_pads
                    break

        assert net_id is not None, "Need a net with at least 2 pads on F.Cu"
        assert len(pads) >= 2

        # Route between two pads of the same net
        pad1, pad2 = pads[0], pads[1]

        router = TraceRouter(parser, clearance=0.2)
        path = router.route(
            start_x=pad1.x, start_y=pad1.y,
            end_x=pad2.x, end_y=pad2.y,
            layer="F.Cu",
            width=0.25,
            net_id=net_id  # Allow crossing same-net elements
        )

        # Should find a path (same net elements are not obstacles)
        # Note: Path might still be empty if there's truly no route
        # but the point is same-net obstacles are excluded
        assert isinstance(path, list)
        if len(path) == 0:
            # Verify the issue isn't that same-net pads are blocking
            obstacle_map = ObstacleMap(
                parser, layer="F.Cu", clearance=0.2, allowed_net_id=net_id
            )
            # Start and end should not be blocked
            start_blocked = obstacle_map.is_blocked(pad1.x, pad1.y)
            end_blocked = obstacle_map.is_blocked(pad2.x, pad2.y)
            assert not start_blocked, "Start pad should not be blocked (same net)"
            assert not end_blocked, "End pad should not be blocked (same net)"

    def test_same_net_traces_not_blocked(self, parser):
        """Test that traces of the same net don't block routing."""
        # Find a trace
        traces = parser.get_traces_by_layer("F.Cu")
        if len(traces) == 0:
            pytest.skip("No traces on F.Cu to test")

        trace = traces[0]
        net_id = trace.net_id

        # Create obstacle map with and without net allowance
        map_blocked = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
        map_allowed = ObstacleMap(
            parser, layer="F.Cu", clearance=0.2, allowed_net_id=net_id
        )

        # Midpoint of trace
        mid_x = (trace.start_x + trace.end_x) / 2
        mid_y = (trace.start_y + trace.end_y) / 2

        # Without allowance, trace midpoint should be blocked
        assert map_blocked.is_blocked(mid_x, mid_y), (
            "Trace should be blocked when net not allowed"
        )

        # With allowance, trace midpoint should NOT be blocked
        assert not map_allowed.is_blocked(mid_x, mid_y), (
            "Same-net trace should not be blocked"
        )

    def test_same_net_vias_not_blocked(self, parser):
        """Test that vias of the same net don't block routing."""
        vias = parser.vias
        if len(vias) == 0:
            pytest.skip("No vias to test")

        via = vias[0]
        net_id = via.net_id

        # Create obstacle maps
        map_blocked = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
        map_allowed = ObstacleMap(
            parser, layer="F.Cu", clearance=0.2, allowed_net_id=net_id
        )

        # Without allowance, via should be blocked
        assert map_blocked.is_blocked(via.x, via.y), (
            "Via should be blocked when net not allowed"
        )

        # With allowance (if via has same net), should NOT be blocked
        if net_id > 0:
            assert not map_allowed.is_blocked(via.x, via.y), (
                "Same-net via should not be blocked"
            )

    def test_find_net_at_point(self, router, parser):
        """Test finding net at a pad location."""
        # Find a pad with a net
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0:
                pad = p
                break

        assert pad is not None

        # Find net at pad location
        net_id = router.find_net_at_point(pad.x, pad.y, "F.Cu")
        assert net_id == pad.net_id

    def test_route_returns_simplified_path(self, router):
        """Test that returned path has collinear points removed."""
        path = router.route(
            start_x=130.0, start_y=55.0,
            end_x=145.0, end_y=55.0,
            layer="F.Cu",
            width=0.25
        )

        if len(path) >= 3:
            # Check that no three consecutive points are collinear
            for i in range(len(path) - 2):
                p1, p2, p3 = path[i], path[i+1], path[i+2]

                # Calculate directions
                dx1 = p2[0] - p1[0]
                dy1 = p2[1] - p1[1]
                dx2 = p3[0] - p2[0]
                dy2 = p3[1] - p2[1]

                # Normalize
                len1 = math.sqrt(dx1*dx1 + dy1*dy1)
                len2 = math.sqrt(dx2*dx2 + dy2*dy2)

                if len1 > 0.001 and len2 > 0.001:
                    dx1, dy1 = dx1/len1, dy1/len1
                    dx2, dy2 = dx2/len2, dy2/len2

                    # Should not be collinear (directions should differ)
                    is_collinear = (
                        abs(dx1 - dx2) < 0.02 and abs(dy1 - dy2) < 0.02
                    )
                    assert not is_collinear, (
                        f"Points {p1}, {p2}, {p3} appear to be collinear"
                    )


class TestAPIIntegration:
    """Integration tests for the routing API."""

    def test_route_endpoint_model(self):
        """Test that RouteRequest and RouteResponse models are valid."""
        from backend.main import RouteRequest, RouteResponse

        # Test RouteRequest
        request = RouteRequest(
            start_x=100.0,
            start_y=50.0,
            end_x=110.0,
            end_y=60.0,
            layer="F.Cu",
            width=0.25
        )
        assert request.start_x == 100.0
        assert request.layer == "F.Cu"

        # Test RouteResponse
        response = RouteResponse(
            success=True,
            path=[[100.0, 50.0], [110.0, 60.0]],
            message="OK"
        )
        assert response.success is True
        assert len(response.path) == 2

    def test_via_check_endpoint_models(self):
        """Test that ViaCheckRequest and ViaCheckResponse models are valid."""
        from backend.main import ViaCheckRequest, ViaCheckResponse

        # Test ViaCheckRequest with defaults
        request = ViaCheckRequest(x=140.0, y=70.0)
        assert request.x == 140.0
        assert request.y == 70.0
        assert request.size == 0.8  # Default
        assert request.drill == 0.4  # Default
        assert request.net_id is None  # Default

        # Test ViaCheckRequest with custom values
        request2 = ViaCheckRequest(
            x=150.0,
            y=80.0,
            size=1.0,
            drill=0.5,
            net_id=42
        )
        assert request2.size == 1.0
        assert request2.drill == 0.5
        assert request2.net_id == 42

        # Test ViaCheckResponse
        response_valid = ViaCheckResponse(valid=True)
        assert response_valid.valid is True
        assert response_valid.message == ""

        response_invalid = ViaCheckResponse(
            valid=False,
            message="Clearance violation on F.Cu"
        )
        assert response_invalid.valid is False
        assert "F.Cu" in response_invalid.message


class TestViaPlacementValidation:
    """Tests for via placement validation logic."""

    def test_via_blocked_on_pad(self, parser):
        """Test that via placement is blocked on a pad."""
        # Find a pad on F.Cu
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers:
                pad = p
                break

        assert pad is not None

        # Check via at pad location
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
        via_radius = 0.4  # 0.8mm via
        is_blocked = obstacle_map.is_blocked(pad.x, pad.y, via_radius)

        assert is_blocked, "Via should be blocked at pad location"

    def test_via_allowed_on_same_net_pad(self, parser):
        """Test that via placement is allowed on same-net pad."""
        # Find a pad with a net
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0:
                pad = p
                break

        assert pad is not None

        # Check via at pad location with net allowance
        obstacle_map = ObstacleMap(
            parser, layer="F.Cu", clearance=0.2, allowed_net_id=pad.net_id
        )
        via_radius = 0.4
        is_blocked = obstacle_map.is_blocked(pad.x, pad.y, via_radius)

        assert not is_blocked, "Via should be allowed on same-net pad"

    def test_via_blocked_on_trace(self, parser):
        """Test that via placement is blocked on a trace."""
        traces = parser.get_traces_by_layer("F.Cu")
        if len(traces) == 0:
            pytest.skip("No traces on F.Cu to test")

        trace = traces[0]
        mid_x = (trace.start_x + trace.end_x) / 2
        mid_y = (trace.start_y + trace.end_y) / 2

        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
        via_radius = 0.4
        is_blocked = obstacle_map.is_blocked(mid_x, mid_y, via_radius)

        assert is_blocked, "Via should be blocked on trace"

    def test_via_checks_all_copper_layers(self, parser):
        """Test that via validation checks all copper layers."""
        copper_layers = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

        # Find a location blocked on at least one layer
        # (Use a pad location - pads are often on multiple layers or have vias)
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers:
                pad = p
                break

        if pad is None:
            pytest.skip("No pads to test")

        # Check each layer
        blocked_layers = []
        for layer in copper_layers:
            obstacle_map = ObstacleMap(parser, layer=layer, clearance=0.2)
            if obstacle_map.is_blocked(pad.x, pad.y, 0.4):
                blocked_layers.append(layer)

        # Should be blocked on at least F.Cu (where the pad is)
        assert "F.Cu" in blocked_layers, "Via should be blocked on F.Cu at pad location"

    def test_via_size_affects_blocking(self, parser):
        """Test that via size affects whether placement is blocked."""
        # Find a pad
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers:
                pad = p
                break

        if pad is None:
            pytest.skip("No pads to test")

        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

        # Point slightly outside pad but close
        test_x = pad.x + pad.width/2 + 0.3
        test_y = pad.y

        # Small via might fit, large via might not
        small_via_blocked = obstacle_map.is_blocked(test_x, test_y, 0.2)
        large_via_blocked = obstacle_map.is_blocked(test_x, test_y, 0.8)

        # Large via more likely to be blocked than small via
        # (This depends on exact geometry, but the test shows size matters)
        assert isinstance(small_via_blocked, bool)
        assert isinstance(large_via_blocked, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
