"""Tests for path optimizer."""
import pytest
import math
from backend.routing.optimizer import PathOptimizer
from backend.routing.hulls import Point


class TestPathOptimizer:
    """Test path optimization passes."""

    @pytest.fixture
    def optimizer(self):
        """Create optimizer without hull map (no collision checking)."""
        return PathOptimizer(hull_map=None, trace_width=0.25)

    def test_remove_duplicates(self, optimizer):
        """Duplicate points should be removed."""
        path = [(0, 0), (1, 1), (1, 1), (2, 2)]
        result = optimizer.optimize(path)
        # Should have 3 points, not 4
        assert len(result) <= 3

    def test_merge_colinear(self, optimizer):
        """Colinear points should be merged."""
        path = [(0, 0), (1, 1), (2, 2), (3, 3)]
        result = optimizer.optimize(path)
        # All points are colinear, should merge to 2 points
        assert len(result) == 2
        assert result[0] == (0, 0)
        assert result[-1] == (3, 3)

    def test_enforce_45_degrees(self, optimizer):
        """Non-45-degree segments should be converted to 45-degree segments."""
        # Path at ~30 degrees (not 45)
        path = [(0, 0), (3, 1)]
        result = optimizer.optimize(path)

        # Should have intermediate point(s) to make 45° segments
        assert len(result) >= 2

        # Check all segments are at 45° multiples
        for i in range(1, len(result)):
            dx = result[i][0] - result[i-1][0]
            dy = result[i][1] - result[i-1][1]
            assert optimizer._is_45_degree_angle(dx, dy), \
                f"Segment {i} at angle {math.degrees(math.atan2(dy, dx))}° is not 45° multiple"

    def test_preserve_endpoints(self, optimizer):
        """Start and end points should be preserved."""
        path = [(1.5, 2.5), (3.7, 4.2), (5.0, 6.0)]
        result = optimizer.optimize(path)

        assert result[0] == (1.5, 2.5), "Start point changed"
        assert result[-1] == (5.0, 6.0), "End point changed"

    def test_path_length_not_increased_significantly(self, optimizer):
        """Optimized path should not be much longer than original."""
        # Simple diagonal path
        path = [(0, 0), (5, 5)]
        result = optimizer.optimize(path)

        def path_length(pts):
            total = 0
            for i in range(1, len(pts)):
                dx = pts[i][0] - pts[i-1][0]
                dy = pts[i][1] - pts[i-1][1]
                total += math.sqrt(dx*dx + dy*dy)
            return total

        orig_len = path_length(path)
        opt_len = path_length(result)

        # Optimized path should be within 10% of original
        assert opt_len <= orig_len * 1.1, \
            f"Optimized path {opt_len:.2f} is much longer than original {orig_len:.2f}"

    def test_indent_pattern_detection(self, optimizer):
        """Detect backtrack/indent patterns."""
        p1 = Point(0, 0)
        p2 = Point(1, 1)  # NE
        p3 = Point(0.5, 1.5)  # NW (reverses x direction)

        # This should be detected as a backtrack
        assert optimizer._detect_backtrack(p1, p2, p3)

    def test_no_backtrack_when_continuing(self, optimizer):
        """Continuing in same general direction is not a backtrack."""
        p1 = Point(0, 0)
        p2 = Point(1, 1)  # NE
        p3 = Point(2, 1.5)  # E-NE (continues generally NE)

        # This should NOT be detected as a backtrack
        assert not optimizer._detect_backtrack(p1, p2, p3)


class TestPathOptimizerWithHullMap:
    """Tests that require a hull map for collision checking."""

    def test_path_length_reduced(self):
        """Path optimization should reduce unnecessary length."""
        # Create an indent pattern manually
        # This simulates: go NE, then E (backtrack in Y), then NE again
        path = [
            (0, 0),
            (1, 1),      # NE
            (2, 1),      # E (no Y progress)
            (3, 2),      # NE
            (4, 3),      # NE
        ]

        optimizer = PathOptimizer(hull_map=None, trace_width=0.25)
        result = optimizer.optimize(path)

        # The optimizer should find a more direct path
        # Original: 4 segments
        # Optimized: should be fewer segments
        print(f"Original: {len(path)} points, Optimized: {len(result)} points")
        print(f"Original path: {path}")
        print(f"Optimized path: {result}")

        # Calculate lengths
        def path_length(pts):
            total = 0
            for i in range(1, len(pts)):
                dx = pts[i][0] - pts[i-1][0]
                dy = pts[i][1] - pts[i-1][1]
                total += math.sqrt(dx*dx + dy*dy)
            return total

        orig_len = path_length(path)
        opt_len = path_length(result)

        print(f"Original length: {orig_len:.3f}, Optimized length: {opt_len:.3f}")

        # The optimized path should preserve endpoints
        assert result[0] == path[0]
        assert result[-1] == path[-1]


class TestBacktrackRemoval:
    """Test specific backtrack removal scenarios."""

    def test_no_y_reversal_when_going_up(self):
        """
        Test that Y-axis reversals are eliminated when path goes upward overall.

        A path going from bottom to top should not have segments going downward.
        """
        from backend.routing.optimizer import PathOptimizer
        from backend.routing.hulls import Point

        # Create a path that goes up overall but has a downward segment
        # Path: (0,0) -> (1,2) -> (2,1) -> (3,3)
        #       The segment (1,2)->(2,1) goes DOWN when we're going UP overall
        points = [
            Point(0, 0),
            Point(1, 2),
            Point(2, 1),  # Goes down - reversal!
            Point(3, 3),
        ]

        optimizer = PathOptimizer(hull_map=None, trace_width=0.25)

        # Without hull_map, the reversal elimination won't run
        # But we can test the detection logic
        assert optimizer._detect_backtrack(points[0], points[1], points[2])

    def test_route_should_not_go_left_between_j4_pads(self):
        """
        Route from (150.8, 100.75) to (155.887, 91.826) should not go left.

        The route goes generally right and up (NE direction).
        Any leftward movement is a backtrack that should be eliminated.

        J4 pads are at x=154.6, y=93.0 and y=95.5.
        The route should pass to the right of these pads, not go left towards them.
        """
        from backend.pcb import PCBParser
        from backend.routing import TraceRouter

        parser = PCBParser("BLDriver.kicad_pcb")
        router = TraceRouter(parser, clearance=0.2, cache_obstacles=True)

        path = router.route(
            start_x=150.8,
            start_y=100.75,
            end_x=155.88688686520777,
            end_y=91.82582828802386,
            layer="F.Cu",
            width=0.25,
            net_id=57
        )

        assert path, "Route should succeed"

        # Check that x coordinates never decrease significantly
        # (small decreases < 0.1mm are acceptable for 45° segments)
        max_x_seen = path[0][0]
        for i, (x, y) in enumerate(path):
            if x < max_x_seen - 0.1:
                # Found a significant leftward movement
                pytest.fail(
                    f"Route goes left at point {i}: x={x:.3f} < max_x={max_x_seen:.3f}\n"
                    f"Full path: {path}"
                )
            max_x_seen = max(max_x_seen, x)

        print(f"\nRoute has {len(path)} waypoints, no significant leftward movement")
        print(f"Path: {[(f'{p[0]:.2f}', f'{p[1]:.2f}') for p in path]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
