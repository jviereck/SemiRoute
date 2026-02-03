"""Tests for the AutoRouter class."""
import pytest
from unittest.mock import MagicMock, patch

from backend.routing import TraceRouter, AutoRouter
from backend.routing.autorouter import AutoRouteResult, AutoRouteSegment, AutoRouteVia


# Marker for slow integration tests that run A* on real PCB data
slow = pytest.mark.slow


@pytest.fixture
def mock_trace_router():
    """Create a mock TraceRouter for unit testing."""
    router = MagicMock(spec=TraceRouter)
    return router


@pytest.fixture
def auto_router(mock_trace_router):
    """Create an AutoRouter with mock dependencies."""
    return AutoRouter(mock_trace_router, via_size=0.8, via_drill=0.4)


class TestAutoRouterUnit:
    """Unit tests using mocked TraceRouter."""

    def test_single_layer_success(self, auto_router, mock_trace_router):
        """Test successful routing on a single layer."""
        # Mock route() to succeed on first call
        expected_path = [(0, 0), (1, 0), (2, 0), (3, 0)]
        mock_trace_router.route.return_value = expected_path

        result = auto_router.auto_route(
            start_x=0, start_y=0,
            end_x=3, end_y=0,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=1
        )

        assert result.success
        assert len(result.segments) == 1
        assert result.segments[0].path == expected_path
        assert result.segments[0].layer == "F.Cu"
        assert len(result.vias) == 0
        assert "F.Cu" in result.message

    def test_fallback_to_alternate_layer(self, auto_router, mock_trace_router):
        """Test fallback when preferred layer is blocked."""
        # Mock route() to fail on F.Cu but succeed on B.Cu
        alternate_path = [(0, 0), (1, 1), (3, 0)]

        def route_side_effect(start_x, start_y, end_x, end_y, layer, width, net_id):
            if layer == "F.Cu":
                return []  # Blocked
            elif layer == "B.Cu":
                return alternate_path
            return []

        mock_trace_router.route.side_effect = route_side_effect

        result = auto_router.auto_route(
            start_x=0, start_y=0,
            end_x=3, end_y=0,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=1
        )

        assert result.success
        assert len(result.segments) == 1
        assert result.segments[0].layer == "B.Cu"
        assert len(result.vias) == 0

    def test_single_via_routing(self, auto_router, mock_trace_router):
        """Test routing with a single via when direct path blocked."""
        path1 = [(0, 0), (1.5, 0)]  # Start to via
        path2 = [(1.5, 0), (3, 0)]  # Via to end

        call_count = [0]

        def route_side_effect(start_x, start_y, end_x, end_y, layer, width, net_id):
            call_count[0] += 1
            # First calls: fail direct routes on all layers
            if abs(end_x - 3) < 0.01 and abs(start_x - 0) < 0.01:
                return []  # Direct route blocked

            # Via routing: succeed on F.Cu -> via
            if abs(start_x - 0) < 0.01 and abs(start_y - 0) < 0.01 and layer == "F.Cu":
                return path1

            # Via routing: succeed on B.Cu via -> end
            if abs(start_x - 1.5) < 0.1 and abs(start_y - 0) < 0.1 and layer == "B.Cu":
                return path2

            return []

        mock_trace_router.route.side_effect = route_side_effect
        mock_trace_router.check_via_placement.return_value = (True, "")

        result = auto_router.auto_route(
            start_x=0, start_y=0,
            end_x=3, end_y=0,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=1
        )

        assert result.success
        assert len(result.segments) == 2
        assert result.segments[0].layer == "F.Cu"
        assert result.segments[1].layer == "B.Cu"
        assert len(result.vias) == 1

    def test_via_blocked(self, auto_router, mock_trace_router):
        """Test failure when via placement is blocked."""
        # All direct routes blocked
        mock_trace_router.route.return_value = []
        # Via placement blocked
        mock_trace_router.check_via_placement.return_value = (False, "Clearance violation")

        result = auto_router.auto_route(
            start_x=0, start_y=0,
            end_x=3, end_y=0,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=1,
            max_vias=1  # Limit to single via attempts
        )

        assert not result.success
        assert "blocked" in result.message.lower()

    def test_all_paths_blocked(self, auto_router, mock_trace_router):
        """Test failure when all paths are blocked."""
        mock_trace_router.route.return_value = []
        mock_trace_router.check_via_placement.return_value = (True, "")

        result = auto_router.auto_route(
            start_x=0, start_y=0,
            end_x=3, end_y=0,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=1
        )

        assert not result.success
        assert "blocked" in result.message.lower()


class TestViaCandidateGeneration:
    """Tests for via candidate generation."""

    def test_via_candidates_along_path(self, auto_router, mock_trace_router):
        """Test that via candidates are generated along the direct path."""
        candidates = auto_router._generate_via_candidates(0, 0, 4, 0)

        # Should have candidates at 25%, 50%, 75%
        assert any(abs(c[0] - 1.0) < 0.1 for c in candidates)  # 25%
        assert any(abs(c[0] - 2.0) < 0.1 for c in candidates)  # 50%
        assert any(abs(c[0] - 3.0) < 0.1 for c in candidates)  # 75%

    def test_via_candidates_perpendicular_offset(self, auto_router, mock_trace_router):
        """Test that via candidates include perpendicular offsets."""
        candidates = auto_router._generate_via_candidates(0, 0, 4, 0)

        # Should have candidates offset perpendicular to the path (y != 0)
        offset_candidates = [c for c in candidates if abs(c[1]) > 0.5]
        assert len(offset_candidates) > 0

    def test_via_candidates_short_path(self, auto_router, mock_trace_router):
        """Test via candidates for very short paths."""
        candidates = auto_router._generate_via_candidates(0, 0, 0.001, 0)

        # Should still return at least one candidate (the start/end point)
        assert len(candidates) >= 1


@slow
class TestAutoRouterIntegration:
    """Integration tests using real PCB data."""

    @pytest.fixture
    def real_auto_router(self, cached_router):
        """Create AutoRouter with real TraceRouter."""
        return AutoRouter(cached_router, via_size=0.8, via_drill=0.4)

    def test_auto_route_clear_path(self, real_auto_router, parser):
        """Test auto-routing when path is clear."""
        # Find two pads on same net that should have a clear path
        pads_by_net = {}
        for pad in parser.pads:
            if "F.Cu" in pad.layers and pad.net_id > 0:
                if pad.net_id not in pads_by_net:
                    pads_by_net[pad.net_id] = []
                pads_by_net[pad.net_id].append(pad)

        # Find a net with at least 2 pads
        test_net = None
        test_pads = None
        for net_id, pads in pads_by_net.items():
            if len(pads) >= 2:
                test_net = net_id
                test_pads = pads[:2]
                break

        if not test_pads:
            pytest.skip("No suitable test pads found")

        result = real_auto_router.auto_route(
            start_x=test_pads[0].x,
            start_y=test_pads[0].y,
            end_x=test_pads[1].x,
            end_y=test_pads[1].y,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=test_net
        )

        # Should find some route (may or may not need vias)
        assert result.success
        assert len(result.segments) >= 1
        # Each segment should have a valid path
        for seg in result.segments:
            assert len(seg.path) >= 2
            assert seg.layer in ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

    def test_auto_route_returns_result_structure(self, real_auto_router, parser):
        """Test that auto-route returns proper result structure."""
        # Find any pad to start from
        pad = None
        for p in parser.pads:
            if "F.Cu" in p.layers and p.net_id > 0:
                pad = p
                break

        if not pad:
            pytest.skip("No suitable pad found")

        result = real_auto_router.auto_route(
            start_x=pad.x,
            start_y=pad.y,
            end_x=pad.x + 1,  # 1mm away
            end_y=pad.y,
            preferred_layer="F.Cu",
            width=0.25,
            net_id=pad.net_id
        )

        # Result should have proper structure
        assert isinstance(result, AutoRouteResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.segments, list)
        assert isinstance(result.vias, list)
        assert isinstance(result.message, str)

        for seg in result.segments:
            assert isinstance(seg, AutoRouteSegment)
            assert isinstance(seg.path, list)
            assert isinstance(seg.layer, str)

        for via in result.vias:
            assert isinstance(via, AutoRouteVia)
            assert isinstance(via.x, float)
            assert isinstance(via.y, float)
            assert isinstance(via.size, float)
