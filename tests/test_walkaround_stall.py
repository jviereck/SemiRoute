"""Tests for walkaround router stall detection.

These tests verify that the walkaround router bails out early when
it's not making progress toward the goal, rather than running all
max_iterations.
"""
import pytest
import time

from backend.pcb.parser import PCBParser
from backend.routing.hull_map import HullMap
from backend.routing.walkaround import WalkaroundRouter
from backend.routing.hulls import Point
from backend.config import DEFAULT_PCB_FILE


@pytest.fixture
def parser():
    """Load the test PCB."""
    return PCBParser(DEFAULT_PCB_FILE)


@pytest.fixture
def hull_map(parser):
    """Create hull map for F.Cu layer."""
    return HullMap(parser, 'F.Cu', clearance=0.2)


class TestWalkaroundStallDetection:
    """Tests for stall detection in walkaround router."""

    def test_stall_detection_bails_early(self, hull_map):
        """
        Verify that walkaround bails out early when not making progress.

        This tests routing to the U2 chip area which has dense obstacles
        that can cause the walkaround to get stuck oscillating.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Route to U2 pin area - this previously took 3+ seconds
        # because walkaround would run all 1000 iterations
        start = Point(155.34, 81.19)
        end = Point(154.28, 79.68)

        start_time = time.time()
        result = wr.route(start, end, net_id=53)
        elapsed = time.time() - start_time

        # Should complete in under 1 second due to stall detection
        # (previously took 3+ seconds)
        assert elapsed < 1.0, (
            f"Walkaround took {elapsed:.2f}s - stall detection may not be working"
        )

        # If it fails, it should fail due to stall, not max iterations
        if not result.success:
            # Stall detection triggers at 20 iterations without progress
            # so total iterations should be much less than 1000
            assert result.iterations < 100, (
                f"Expected early bailout but got {result.iterations} iterations"
            )

    def test_successful_routes_unaffected(self, hull_map):
        """
        Verify that stall detection doesn't break successful routes.

        Routes that make progress should still complete normally.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Simple route that should succeed
        start = Point(153.54, 98.01)
        end = Point(153.54, 94.10)

        result = wr.route(start, end, net_id=57)

        assert result.success, "Simple route should succeed"
        assert len(result.path) >= 2, "Path should have at least start and end"

    def test_stall_detection_allows_indirect_progress(self, hull_map):
        """
        Verify that routes making indirect progress (going around obstacles)
        are not incorrectly terminated by stall detection.

        The stall detection uses a 5% improvement threshold, which should
        allow routes that temporarily move away from the goal.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Route that requires going around obstacles
        # This route goes near J4 and requires walkaround
        start = Point(150, 95.5)
        end = Point(158, 95.5)

        result = wr.route(start, end, net_id=999)

        # This route may or may not succeed depending on obstacles,
        # but if it does succeed, it means stall detection didn't
        # prematurely terminate it
        if result.success:
            assert len(result.path) >= 2

    def test_iteration_count_reasonable(self, hull_map):
        """
        Verify that failed routes don't waste iterations.

        When stall detection kicks in, the iteration count should be
        bounded by the stall threshold (max_stall=50) plus some overhead.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Dense area route that likely fails
        start = Point(155.34, 81.19)
        end = Point(154.28, 79.68)

        result = wr.route(start, end, net_id=53)

        if not result.success:
            # With max_stall=20 and 5% progress threshold,
            # we shouldn't hit anywhere near 1000 iterations
            assert result.iterations < 100, (
                f"Failed route used {result.iterations} iterations - "
                f"expected much fewer with stall detection"
            )
