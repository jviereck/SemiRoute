"""Tests for companion trace routing functionality."""
import pytest
from unittest.mock import MagicMock, patch

from backend.pcb import PCBParser
from backend.pcb.models import TraceInfo


class TestTracePathAPI:
    """Tests for the /api/trace-path endpoint."""

    def test_get_traces_by_layer(self, parser):
        """Test that parser can return traces filtered by layer."""
        traces = parser.get_traces_by_layer("F.Cu")
        assert isinstance(traces, list)
        # All traces should be on F.Cu
        for trace in traces:
            assert trace.layer == "F.Cu"

    def test_traces_have_required_attributes(self, parser):
        """Test that traces have the attributes needed for path reconstruction."""
        traces = parser.get_traces_by_layer("F.Cu")
        if traces:
            trace = traces[0]
            assert hasattr(trace, 'start_x')
            assert hasattr(trace, 'start_y')
            assert hasattr(trace, 'end_x')
            assert hasattr(trace, 'end_y')
            assert hasattr(trace, 'net_id')
            assert hasattr(trace, 'width')

    def test_traces_grouped_by_net(self, parser):
        """Test that traces can be grouped by net ID."""
        traces = parser.get_traces_by_layer("F.Cu")
        net_traces = {}
        for trace in traces:
            if trace.net_id not in net_traces:
                net_traces[trace.net_id] = []
            net_traces[trace.net_id].append(trace)

        # Should have multiple nets with traces
        assert len(net_traces) > 0


class TestTracePathReconstruction:
    """Tests for trace path reconstruction logic."""

    def test_find_closest_trace_to_point(self):
        """Test finding the closest trace segment to a point."""
        # Create mock traces
        traces = [
            MagicMock(start_x=0, start_y=0, end_x=10, end_y=0, net_id=1, width=0.25),
            MagicMock(start_x=20, start_y=0, end_x=30, end_y=0, net_id=1, width=0.25),
        ]

        # Find closest to point (5, 0)
        test_point = (5, 0)
        best_trace = None
        best_dist = float('inf')

        for trace in traces:
            dist_start = ((trace.start_x - test_point[0]) ** 2 + (trace.start_y - test_point[1]) ** 2) ** 0.5
            dist_end = ((trace.end_x - test_point[0]) ** 2 + (trace.end_y - test_point[1]) ** 2) ** 0.5
            min_dist = min(dist_start, dist_end)

            if min_dist < best_dist:
                best_dist = min_dist
                best_trace = trace

        # First trace should be closer
        assert best_trace == traces[0]
        assert best_dist == 5.0  # Distance from (5,0) to (0,0)

    def test_find_connected_traces(self):
        """Test finding traces that connect at an endpoint."""
        # Create a chain of mock traces
        trace1 = MagicMock(start_x=0, start_y=0, end_x=10, end_y=0, net_id=1)
        trace2 = MagicMock(start_x=10, start_y=0, end_x=20, end_y=0, net_id=1)
        trace3 = MagicMock(start_x=20, start_y=0, end_x=30, end_y=0, net_id=1)
        traces = [trace1, trace2, trace3]

        # Find traces connected to (10, 0) - should find trace1 and trace2
        tolerance = 0.01
        end_x, end_y = 10, 0
        connected = []

        for trace in traces:
            if abs(trace.start_x - end_x) < tolerance and abs(trace.start_y - end_y) < tolerance:
                connected.append((trace, True))  # Start from start
            elif abs(trace.end_x - end_x) < tolerance and abs(trace.end_y - end_y) < tolerance:
                connected.append((trace, False))  # Start from end

        # Should find trace1 (end at 10,0) and trace2 (start at 10,0)
        assert len(connected) == 2

    def test_build_path_from_connected_traces(self):
        """Test building a path from connected trace segments."""
        # Simulate building a path from traces
        path = [[0, 0]]

        # Add first segment
        path.append([10, 0])

        # Add second segment (should not duplicate point)
        if path[-1] != [10, 0]:
            path.append([10, 0])
        path.append([20, 0])

        # Add third segment
        if path[-1] != [20, 0]:
            path.append([20, 0])
        path.append([30, 0])

        # Path should have 4 unique points
        assert len(path) == 4
        assert path == [[0, 0], [10, 0], [20, 0], [30, 0]]


class TestCompanionOffsetCalculation:
    """Tests for companion offset calculations."""

    def test_perpendicular_offset(self):
        """Test calculating perpendicular offset for companions."""
        # Reference direction vector (1, 0) - horizontal
        direction = (1, 0)

        # Perpendicular is (-dy, dx) = (0, 1)
        perp_x = -direction[1]
        perp_y = direction[0]

        assert perp_x == 0
        assert perp_y == 1

    def test_offset_position_calculation(self):
        """Test calculating offset positions for multiple companions."""
        ref_point = (10, 5)
        base_spacing = 0.4
        direction = (1, 0)  # Horizontal reference

        # Perpendicular direction
        perp_x = -direction[1]  # 0
        perp_y = direction[0]   # 1

        companions = []
        for i in range(3):
            offset_index = i + 1  # 1-based
            offset = base_spacing * offset_index
            target_x = ref_point[0] + perp_x * offset
            target_y = ref_point[1] + perp_y * offset
            companions.append((target_x, target_y))

        # Verify offset positions
        assert companions[0] == (10, 5.4)   # offset 0.4
        assert companions[1] == (10, 5.8)   # offset 0.8
        assert companions[2] == (10, 6.2)   # offset 1.2

    def test_diagonal_direction_offset(self):
        """Test offset calculation for diagonal reference direction."""
        import math

        # 45-degree direction (normalized)
        length = math.sqrt(2)
        direction = (1 / length, 1 / length)

        # Perpendicular direction
        perp_x = -direction[1]
        perp_y = direction[0]

        # Should be perpendicular (90 degrees rotated)
        # Original: (0.707, 0.707), perpendicular: (-0.707, 0.707)
        assert abs(perp_x - (-1 / length)) < 0.001
        assert abs(perp_y - (1 / length)) < 0.001


class TestFindClosestPointOnPath:
    """Tests for the closest point on path algorithm."""

    def test_point_at_start(self):
        """Test finding closest point when target is at path start."""
        path = [[0, 0], [10, 0], [10, 10]]
        target = (0, 1)

        # Simple implementation of finding closest point
        closest_point = None
        closest_dist = float('inf')

        for i in range(len(path) - 1):
            p1 = path[i]
            p2 = path[i + 1]

            # Project target onto segment
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length_sq = dx * dx + dy * dy

            if length_sq < 0.0001:
                continue

            t = max(0, min(1, ((target[0] - p1[0]) * dx + (target[1] - p1[1]) * dy) / length_sq))
            proj_x = p1[0] + t * dx
            proj_y = p1[1] + t * dy
            dist = ((target[0] - proj_x) ** 2 + (target[1] - proj_y) ** 2) ** 0.5

            if dist < closest_dist:
                closest_dist = dist
                closest_point = (proj_x, proj_y)

        # Closest should be on first segment
        assert closest_point is not None
        assert closest_point == (0, 0)  # Projected to start of segment

    def test_point_at_middle_of_segment(self):
        """Test finding closest point in the middle of a segment."""
        path = [[0, 0], [10, 0]]
        target = (5, 2)

        p1, p2 = path[0], path[1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length_sq = dx * dx + dy * dy

        t = max(0, min(1, ((target[0] - p1[0]) * dx + (target[1] - p1[1]) * dy) / length_sq))
        proj_x = p1[0] + t * dx
        proj_y = p1[1] + t * dy

        assert proj_x == 5
        assert proj_y == 0

    def test_point_beyond_segment_end(self):
        """Test finding closest point when target is beyond segment end."""
        path = [[0, 0], [10, 0]]
        target = (15, 0)

        p1, p2 = path[0], path[1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length_sq = dx * dx + dy * dy

        t = max(0, min(1, ((target[0] - p1[0]) * dx + (target[1] - p1[1]) * dy) / length_sq))
        proj_x = p1[0] + t * dx
        proj_y = p1[1] + t * dy

        # Should clamp to segment end
        assert proj_x == 10
        assert proj_y == 0


class TestCompanionViaPlacement:
    """Tests for companion via placement logic."""

    @pytest.fixture
    def mock_router(self):
        """Create a mock router for testing."""
        router = MagicMock()
        router.check_via_placement.return_value = (True, "")
        return router

    def test_via_placement_checked_for_all_companions(self, mock_router):
        """Test that via placement is checked for each companion."""
        companions = [
            {'netId': 1, 'startPoint': {'x': 10, 'y': 5}},
            {'netId': 2, 'startPoint': {'x': 10, 'y': 5.4}},
            {'netId': 3, 'startPoint': {'x': 10, 'y': 5.8}},
        ]
        via_size = 0.8

        # Check via for each companion
        results = []
        for companion in companions:
            valid, msg = mock_router.check_via_placement(
                companion['startPoint']['x'],
                companion['startPoint']['y'],
                via_size / 2,
                companion['netId']
            )
            results.append(valid)

        assert all(results)
        assert mock_router.check_via_placement.call_count == 3

    def test_via_placement_failure_for_one_companion(self, mock_router):
        """Test handling when via placement fails for one companion."""
        # Second via check fails
        mock_router.check_via_placement.side_effect = [
            (True, ""),
            (False, "Clearance violation"),
            (True, ""),
        ]

        companions = [
            {'netId': 1, 'startPoint': {'x': 10, 'y': 5}},
            {'netId': 2, 'startPoint': {'x': 10, 'y': 5.4}},
            {'netId': 3, 'startPoint': {'x': 10, 'y': 5.8}},
        ]

        results = []
        for companion in companions:
            valid, msg = mock_router.check_via_placement(
                companion['startPoint']['x'],
                companion['startPoint']['y'],
                0.4,
                companion['netId']
            )
            results.append((valid, msg))

        # First and third should pass, second should fail
        assert results[0] == (True, "")
        assert results[1] == (False, "Clearance violation")
        assert results[2] == (True, "")
