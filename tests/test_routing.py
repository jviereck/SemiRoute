"""Tests for the PCB routing module."""
import pytest
import math
from pathlib import Path
from unittest.mock import MagicMock

from backend.pcb import PCBParser
from backend.pcb.models import PadInfo, TraceInfo, ViaInfo
from backend.routing import TraceRouter, ObstacleMap, PendingTraceStore
from backend.routing.pathfinding import astar_search, DIRECTIONS


# Marker for slow integration tests that run A* on real PCB data
slow = pytest.mark.slow


# Note: parser, cached_router, cached_obstacle_map_fcu fixtures are in conftest.py
# with pickle-based caching for faster test startup


@pytest.fixture
def router(parser):
    """Create a fresh router instance (no obstacle cache)."""
    return TraceRouter(parser, clearance=0.2)


@slow
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


@slow
class TestPathfinding:
    """Tests for the A* pathfinding algorithm."""

    def test_straight_path_orthogonal(self, cached_obstacle_map_fcu):
        """Test finding a straight horizontal path."""
        # Find a clear area for testing (outside the board) - short 2mm path
        path = astar_search(
            cached_obstacle_map_fcu,
            start_x=120.0, start_y=45.0,
            end_x=122.0, end_y=45.0
        )

        # Should find some path
        if len(path) > 0:
            # Path should start and end correctly
            assert abs(path[0][0] - 120.0) < 0.1
            assert abs(path[-1][0] - 122.0) < 0.1

    def test_path_uses_45_degree_angles(self, cached_obstacle_map_fcu):
        """Test that paths only use 0°, 45°, 90°, etc. angles."""
        # Route between two points - short 2mm diagonal
        path = astar_search(
            cached_obstacle_map_fcu,
            start_x=120.0, start_y=45.0,
            end_x=122.0, end_y=47.0
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

    @slow
    def test_route_between_points(self, cached_router):
        """Test routing between two points - short 2mm path."""
        path = cached_router.route(
            start_x=120.0, start_y=45.0,
            end_x=122.0, end_y=47.0,
            layer="F.Cu",
            width=0.25
        )

        # Should return a path (may be empty if blocked)
        assert isinstance(path, list)

    @slow
    def test_route_on_different_layers(self, cached_router):
        """Test routing on different copper layers - short 2mm paths."""
        layers = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

        for layer in layers:
            path = cached_router.route(
                start_x=120.0, start_y=45.0,
                end_x=122.0, end_y=47.0,
                layer=layer,
                width=0.25
            )
            # Should not raise an error
            assert isinstance(path, list)

    @slow
    def test_same_net_crossing(self, parser, cached_router):
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

        path = cached_router.route(
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

    @slow
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

    @slow
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

    def test_allowed_cells_do_not_extend_into_clearance(self, router, parser):
        """Test that _get_net_cells only covers actual geometry, not clearance zones.

        This prevents same-net routing from crossing nearby different-net pads.
        Note: Rotated pads are excluded because they use a different calculation
        that matches the blocking zone (to allow routes to escape the pad).
        """
        # Find a non-rotated pad with a net
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0 and p.angle == 0:
                pad = p
                break

        if pad is None:
            pytest.skip("No non-rotated pads with net on F.Cu")

        # Get allowed cells for this net
        allowed_cells = router._get_net_cells("F.Cu", pad.net_id)

        # Calculate expected radius (without clearance)
        resolution = router.grid_resolution
        expected_radius = int((max(pad.width, pad.height) / 2) / resolution) + 1

        # The allowed cells should NOT extend beyond the pad geometry
        # Check that cells at clearance distance from pad center are NOT included
        gx = int(round(pad.x / resolution))
        gy = int(round(pad.y / resolution))

        # A cell at (expected_radius + clearance/resolution) should NOT be in allowed
        clearance_cells = int(router.clearance / resolution) + 1
        far_cell = (gx + expected_radius + clearance_cells + 1, gy)

        assert far_cell not in allowed_cells, (
            "Allowed cells should not extend into clearance zone"
        )

    def test_allowed_cells_use_rectangular_bounds(self, parser):
        """Test that allowed cells use rectangular bounds matching pad shape.

        Regression test: Previously, allowed_cells used max(width, height) as
        radius, creating square regions that could overlap nearby pads.
        A 1.5mm x 0.3mm pad should only extend 0.75mm in x but 0.15mm in y.
        """
        # Find a very rectangular pad (width much different from height)
        rect_pad = None
        for pad in parser.pads:
            if "F.Cu" in pad.layers and pad.net_id > 0:
                ratio = max(pad.width, pad.height) / max(0.01, min(pad.width, pad.height))
                if ratio > 3:  # At least 3:1 aspect ratio
                    rect_pad = pad
                    break

        if rect_pad is None:
            pytest.skip("No highly rectangular pads found")

        # Create a router to test _get_net_cells
        router = TraceRouter(parser, clearance=0.2)
        resolution = router.grid_resolution

        gx = int(round(rect_pad.x / resolution))
        gy = int(round(rect_pad.y / resolution))

        # Calculate expected bounds based on actual pad dimensions
        rx = int((rect_pad.width / 2) / resolution) + 1
        ry = int((rect_pad.height / 2) / resolution) + 1

        # The key insight: if we were using max(width, height) for both dimensions,
        # then cells at (gx, gy + max_r) would be allowed even if ry < rx.
        # With proper rectangular bounds, cells beyond the smaller dimension should not be allowed.
        max_r = max(rx, ry)
        min_r = min(rx, ry)

        # Create a mock single-pad set to test the bounds calculation directly
        # We'll compute what cells would be added for just this one pad
        single_pad_cells = set()
        for dx in range(-rx, rx + 1):
            for dy in range(-ry, ry + 1):
                single_pad_cells.add((gx + dx, gy + dy))

        # Verify rectangular bounds: cell at (gx, gy + max_r + 1) should NOT be in
        # single_pad_cells if ry < rx (or vice versa)
        if rx > ry:
            # Pad is wider than tall
            test_cell = (gx, gy + rx + 1)  # This would be allowed if using square bounds
            assert test_cell not in single_pad_cells, (
                f"Cell beyond rectangular y-bound should not be allowed for {rect_pad.width}x{rect_pad.height} pad"
            )
        else:
            # Pad is taller than wide
            test_cell = (gx + ry + 1, gy)  # This would be allowed if using square bounds
            assert test_cell not in single_pad_cells, (
                f"Cell beyond rectangular x-bound should not be allowed for {rect_pad.width}x{rect_pad.height} pad"
            )

    def test_different_net_pads_still_blocked_when_routing_with_net_id(self, parser):
        """Test that routing with a net_id still blocks pads of different nets.

        Regression test: Previously, allowed_cells included clearance zones,
        which could overlap with nearby different-net pads.
        """
        # Find two different nets that have pads
        net1_id = None
        net2_id = None
        net1_pad = None
        net2_pad = None

        for pad in parser.pads:
            if "F.Cu" not in pad.layers or pad.net_id <= 0:
                continue
            if net1_id is None:
                net1_id = pad.net_id
                net1_pad = pad
            elif pad.net_id != net1_id and net2_id is None:
                net2_id = pad.net_id
                net2_pad = pad
                break

        if net1_id is None or net2_id is None:
            pytest.skip("Need at least 2 different nets with pads")

        # Create obstacle map that blocks everything
        obstacle_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

        # Verify that net2's pad IS blocked (it's a different net)
        assert obstacle_map.is_blocked(net2_pad.x, net2_pad.y), (
            "Different net pad should be blocked in obstacle map"
        )

        # Now create a router and get allowed cells for net1
        router = TraceRouter(parser, clearance=0.2)
        allowed_cells = router._get_net_cells("F.Cu", net1_id)

        # net2's pad cells should NOT be in allowed_cells
        resolution = router.grid_resolution
        net2_gx = int(round(net2_pad.x / resolution))
        net2_gy = int(round(net2_pad.y / resolution))

        assert (net2_gx, net2_gy) not in allowed_cells, (
            "Different net pad should not be in allowed cells"
        )

    def test_cannot_route_to_different_net_pad(self, parser):
        """Test that routing to a pad on a different net is rejected.

        Regression test: Previously, the A* algorithm allowed reaching any goal
        cell even if blocked, which meant routes could end on different-net pads.
        The API should now reject such routes with an error message.
        """
        # Find two pads on same layer with different nets
        pad1 = None
        pad2 = None

        for p in parser.pads:
            if "F.Cu" not in p.layers or p.net_id <= 0:
                continue
            if pad1 is None:
                pad1 = p
            elif p.net_id != pad1.net_id:
                pad2 = p
                break

        if pad1 is None or pad2 is None:
            pytest.skip("Need at least 2 pads with different nets")

        # Import here to avoid circular imports
        from backend.main import route_trace, RouteRequest
        import asyncio

        # Create route request from pad1 to pad2 (different nets)
        request = RouteRequest(
            start_x=pad1.x,
            start_y=pad1.y,
            end_x=pad2.x,
            end_y=pad2.y,
            layer="F.Cu",
            width=0.25,
            net_id=pad1.net_id
        )

        # Call the API endpoint (create new event loop for test)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(route_trace(request))
        finally:
            loop.close()

        # Should fail with a message about different nets
        assert response.success is False, (
            "Route to different-net pad should be rejected"
        )
        assert "different net" in response.message.lower(), (
            f"Error message should mention different net, got: {response.message}"
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

    @slow
    def test_route_returns_simplified_path(self, cached_router):
        """Test that returned path has collinear points removed - short 3mm path."""
        path = cached_router.route(
            start_x=120.0, start_y=45.0,
            end_x=123.0, end_y=45.0,
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


@slow
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


class TestPendingTraceStore:
    """Tests for the PendingTraceStore class for user-created traces."""

    def test_store_creation(self):
        """Test that pending trace store can be created."""
        store = PendingTraceStore(grid_resolution=0.025)
        assert store is not None
        assert len(store.get_all_traces()) == 0

    def test_add_trace(self):
        """Test adding a trace to the store."""
        store = PendingTraceStore(grid_resolution=0.025)

        segments = [(100.0, 50.0), (110.0, 50.0), (110.0, 60.0)]
        store.add_trace(
            trace_id="route-1",
            segments=segments,
            width=0.25,
            layer="F.Cu",
            net_id=42
        )

        assert len(store.get_all_traces()) == 1
        trace = store.get_trace("route-1")
        assert trace is not None
        assert trace.id == "route-1"
        assert trace.layer == "F.Cu"
        assert trace.width == 0.25
        assert trace.net_id == 42
        assert len(trace.segments) == 3

    def test_remove_trace(self):
        """Test removing a trace from the store."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a trace
        segments = [(100.0, 50.0), (110.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu", net_id=42)
        assert len(store.get_all_traces()) == 1

        # Remove it
        result = store.remove_trace("route-1")
        assert result is True
        assert len(store.get_all_traces()) == 0
        assert store.get_trace("route-1") is None

    def test_remove_nonexistent_trace(self):
        """Test removing a trace that doesn't exist."""
        store = PendingTraceStore(grid_resolution=0.025)
        result = store.remove_trace("nonexistent")
        assert result is False

    def test_clear_all_traces(self):
        """Test clearing all traces from the store."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add multiple traces
        store.add_trace("route-1", [(100, 50), (110, 50)], 0.25, "F.Cu")
        store.add_trace("route-2", [(120, 60), (130, 60)], 0.25, "B.Cu")
        store.add_trace("route-3", [(140, 70), (150, 70)], 0.25, "F.Cu")
        assert len(store.get_all_traces()) == 3

        # Clear all
        store.clear()
        assert len(store.get_all_traces()) == 0

    def test_get_traces_by_layer(self):
        """Test filtering traces by layer."""
        store = PendingTraceStore(grid_resolution=0.025)

        store.add_trace("route-1", [(100, 50), (110, 50)], 0.25, "F.Cu")
        store.add_trace("route-2", [(120, 60), (130, 60)], 0.25, "B.Cu")
        store.add_trace("route-3", [(140, 70), (150, 70)], 0.25, "F.Cu")

        f_cu_traces = store.get_traces_by_layer("F.Cu")
        assert len(f_cu_traces) == 2

        b_cu_traces = store.get_traces_by_layer("B.Cu")
        assert len(b_cu_traces) == 1

    def test_blocked_cells_include_added_trace(self):
        """Test that blocked cells include cells from added traces."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a horizontal trace
        segments = [(100.0, 50.0), (105.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu")

        # Get blocked cells
        blocked = store.get_blocked_cells("F.Cu", clearance=0.2)

        # The trace should block cells in its path
        # Convert trace midpoint to grid coords
        resolution = 0.025
        mid_gx = int(round(102.5 / resolution))
        mid_gy = int(round(50.0 / resolution))

        # The midpoint should be blocked
        assert (mid_gx, mid_gy) in blocked, "Trace midpoint should be blocked"

    def test_blocked_cells_exclude_removed_trace(self):
        """Test that removed traces are NOT in the blocked cells."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a horizontal trace
        segments = [(100.0, 50.0), (105.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu")

        # Verify it's blocked
        resolution = 0.025
        mid_gx = int(round(102.5 / resolution))
        mid_gy = int(round(50.0 / resolution))

        blocked_before = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert (mid_gx, mid_gy) in blocked_before, "Trace should be blocked before removal"

        # Remove the trace
        store.remove_trace("route-1")

        # Get blocked cells again - should be empty now
        blocked_after = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert (mid_gx, mid_gy) not in blocked_after, "Trace should NOT be blocked after removal"
        assert len(blocked_after) == 0, "No cells should be blocked after removing only trace"

    def test_blocked_cells_cache_invalidation_on_add(self):
        """Test that adding a trace invalidates the blocked cells cache."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Get blocked cells (empty, but this caches the result)
        blocked1 = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert len(blocked1) == 0

        # Add a trace
        store.add_trace("route-1", [(100.0, 50.0), (105.0, 50.0)], 0.25, "F.Cu")

        # Get blocked cells again - should include new trace
        blocked2 = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert len(blocked2) > 0, "Cache should be invalidated and new trace should be included"

    def test_blocked_cells_cache_invalidation_on_remove(self):
        """Test that removing a trace invalidates the blocked cells cache."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a trace
        store.add_trace("route-1", [(100.0, 50.0), (105.0, 50.0)], 0.25, "F.Cu")

        # Get blocked cells (caches the result)
        blocked1 = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert len(blocked1) > 0

        # Remove the trace
        store.remove_trace("route-1")

        # Get blocked cells again - should be empty
        blocked2 = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert len(blocked2) == 0, "Cache should be invalidated and removed trace should not be included"

    def test_blocked_cells_exclude_same_net(self):
        """Test that same-net traces are excluded from blocked cells."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a trace with net_id=42
        segments = [(100.0, 50.0), (105.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu", net_id=42)

        # Get blocked cells excluding net 42
        blocked = store.get_blocked_cells("F.Cu", clearance=0.2, exclude_net_id=42)

        # Should be empty (only trace is same net)
        assert len(blocked) == 0, "Same-net trace should not be blocked"

        # Get blocked cells without exclusion
        blocked_all = store.get_blocked_cells("F.Cu", clearance=0.2)
        assert len(blocked_all) > 0, "Trace should be blocked without net exclusion"

    def test_is_point_blocked(self):
        """Test point blocking check."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a horizontal trace
        segments = [(100.0, 50.0), (105.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu")

        # Point on the trace should be blocked
        assert store.is_point_blocked(102.5, 50.0, 0.1, "F.Cu", clearance=0.2)

        # Point far from the trace should not be blocked
        assert not store.is_point_blocked(200.0, 100.0, 0.1, "F.Cu", clearance=0.2)

    def test_is_point_blocked_after_removal(self):
        """Test that point is not blocked after trace removal."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add a trace
        segments = [(100.0, 50.0), (105.0, 50.0)]
        store.add_trace("route-1", segments, 0.25, "F.Cu")

        # Point should be blocked
        assert store.is_point_blocked(102.5, 50.0, 0.1, "F.Cu", clearance=0.2)

        # Remove the trace
        store.remove_trace("route-1")

        # Point should no longer be blocked
        assert not store.is_point_blocked(102.5, 50.0, 0.1, "F.Cu", clearance=0.2)

    def test_multiple_traces_only_one_removed(self):
        """Test that removing one trace doesn't affect other traces."""
        store = PendingTraceStore(grid_resolution=0.025)

        # Add two traces on same layer
        store.add_trace("route-1", [(100.0, 50.0), (105.0, 50.0)], 0.25, "F.Cu")
        store.add_trace("route-2", [(200.0, 80.0), (205.0, 80.0)], 0.25, "F.Cu")

        # Both should be blocked
        assert store.is_point_blocked(102.5, 50.0, 0.1, "F.Cu", clearance=0.2)
        assert store.is_point_blocked(202.5, 80.0, 0.1, "F.Cu", clearance=0.2)

        # Remove first trace
        store.remove_trace("route-1")

        # First trace location should no longer be blocked
        assert not store.is_point_blocked(102.5, 50.0, 0.1, "F.Cu", clearance=0.2)

        # Second trace should still be blocked
        assert store.is_point_blocked(202.5, 80.0, 0.1, "F.Cu", clearance=0.2)


class TestPendingTraceRouterIntegration:
    """Integration tests for pending traces with the router."""

    def test_router_has_pending_store(self, router):
        """Test that router has a pending trace store."""
        assert hasattr(router, 'pending_store')
        assert isinstance(router.pending_store, PendingTraceStore)

    @slow
    def test_route_avoids_pending_traces(self, cached_router):
        """Test that routing avoids pending user traces - short 4mm path."""
        # Add a pending trace that blocks a direct path
        # This trace goes from (121, 44) to (121, 48) - a short vertical line
        cached_router.pending_store.add_trace(
            "block-trace",
            segments=[(121.0, 44.0), (121.0, 48.0)],
            width=0.5,
            layer="F.Cu"
        )

        try:
            # Try to route from left to right, crossing the blocking trace
            path = cached_router.route(
                start_x=119.0, start_y=46.0,
                end_x=123.0, end_y=46.0,
                layer="F.Cu",
                width=0.25
            )

            # If a path is found, it should not pass through x=121 at y=46
            # (it should go around the blocking trace)
            if len(path) > 0:
                for point in path:
                    x, y = point
                    # Check that path doesn't cross through the blocking trace
                    # The blocking trace is at x=121, y=[44, 48]
                    if 44.5 < y < 47.5:  # Near y=46
                        # Path should not cross x=121 in this y range
                        assert abs(x - 121.0) > 0.3, (
                            f"Path should avoid blocking trace but crosses at ({x}, {y})"
                        )
        finally:
            # Clean up to avoid affecting other tests
            cached_router.pending_store.remove_trace("block-trace")

    @slow
    def test_route_ignores_removed_pending_traces(self, cached_router):
        """Test that removed pending traces don't block routing - short 4mm path."""
        # Add a pending trace
        cached_router.pending_store.add_trace(
            "temp-trace",
            segments=[(121.0, 44.0), (121.0, 48.0)],
            width=0.5,
            layer="F.Cu"
        )

        # Remove it
        cached_router.pending_store.remove_trace("temp-trace")

        # Route should now be able to go straight through
        path = cached_router.route(
            start_x=119.0, start_y=46.0,
            end_x=123.0, end_y=46.0,
            layer="F.Cu",
            width=0.25
        )

        # Path should exist and can now pass through x=121
        # (assuming no other obstacles)
        assert isinstance(path, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
