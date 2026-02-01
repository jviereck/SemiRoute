"""Tests for walkaround router offset calculations.

These tests verify that the walkaround router correctly offsets path points
away from hull boundaries, ensuring proper clearance to obstacles.
"""
import pytest
import math

from backend.pcb.parser import PCBParser
from backend.routing.hull_map import HullMap
from backend.routing.walkaround import WalkaroundRouter
from backend.routing.hulls import Point, LineChain
from backend.routing.geometry import GeometryChecker
from backend.config import DEFAULT_PCB_FILE


@pytest.fixture
def parser():
    """Load the test PCB."""
    return PCBParser(DEFAULT_PCB_FILE)


@pytest.fixture
def hull_map(parser):
    """Create hull map for F.Cu layer."""
    return HullMap(parser, 'F.Cu', clearance=0.2)


class TestWalkaroundVertexOffset:
    """Tests for _offset_vertex function."""

    def test_vertex_offset_nonzero(self, hull_map):
        """
        Verify that vertex offsets produce a non-zero offset.

        The offset should be approximately half_width + corner_offset.
        """
        trace_width = 0.25
        corner_offset = 0.1
        expected_offset = trace_width / 2 + corner_offset

        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=trace_width,
            max_iterations=100,
            corner_offset=corner_offset
        )

        # Test on pad hulls
        pad_hulls = [h for h in hull_map.all_hulls() if h.source_type == 'pad']

        for indexed in pad_hulls[:5]:
            hull = indexed.hull

            for i, vertex in enumerate(hull.points):
                offset_vertex = wr._offset_vertex(vertex, hull, i)

                # Offset distance should be approximately expected
                offset_dist = (offset_vertex - vertex).length()

                # Allow some tolerance for bisector angle effects
                assert offset_dist > expected_offset * 0.9, (
                    f"Vertex {i} offset too small: {offset_dist:.3f} < {expected_offset * 0.9:.3f}"
                )

    def test_vertex_offset_uses_edge_normals(self, hull_map):
        """
        Verify that vertex offset direction is based on edge normals.

        The offset direction should be the average of the outward normals
        of the two edges meeting at the vertex.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=100,
            corner_offset=0.1
        )

        # Create a simple square hull for testing
        square = LineChain(points=[
            Point(0, 0),
            Point(1, 0),
            Point(1, 1),
            Point(0, 1),
        ])

        # Expected outward directions for CCW square:
        # Vertex 0 (0,0): edges go right and down, outward is down-left (-1, -1) normalized
        # Vertex 1 (1,0): edges go up and left, outward is down-right (1, -1) normalized
        # Vertex 2 (1,1): edges go left and down, outward is up-right (1, 1) normalized
        # Vertex 3 (0,1): edges go down and right, outward is up-left (-1, 1) normalized

        expected_directions = [
            Point(-1, -1).normalized(),
            Point(1, -1).normalized(),
            Point(1, 1).normalized(),
            Point(-1, 1).normalized(),
        ]

        offset = wr.half_width + wr.corner_offset
        for i in range(4):
            vertex = square.points[i]
            offset_vertex = wr._offset_vertex(vertex, square, i)

            actual_dir = (offset_vertex - vertex).normalized()
            expected_dir = expected_directions[i]

            # Check direction matches
            dot = actual_dir.dot(expected_dir)
            assert dot > 0.99, (
                f"Vertex {i} offset direction wrong: "
                f"expected ({expected_dir.x:.3f}, {expected_dir.y:.3f}), "
                f"got ({actual_dir.x:.3f}, {actual_dir.y:.3f})"
            )


class TestWalkaroundEdgeOffset:
    """Tests for _offset_from_hull function."""

    def test_edge_offset_perpendicular_to_edge(self, hull_map):
        """
        Verify that edge offsets are perpendicular to the edge.
        """
        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=100,
            corner_offset=0.1
        )

        # Create a simple square hull
        square = LineChain(points=[
            Point(0, 0),
            Point(1, 0),
            Point(1, 1),
            Point(0, 1),
        ])

        # Test midpoint of each edge
        for edge_idx in range(4):
            e1, e2 = square.get_edge(edge_idx)
            midpoint = Point((e1.x + e2.x) / 2, (e1.y + e2.y) / 2)

            offset_point = wr._offset_from_hull(midpoint, square, edge_idx)

            # Offset direction should be perpendicular to edge
            edge_dir = (e2 - e1).normalized()
            offset_dir = (offset_point - midpoint).normalized()

            # Dot product should be ~0 (perpendicular)
            dot = abs(edge_dir.dot(offset_dir))
            assert dot < 0.01, (
                f"Edge {edge_idx} offset not perpendicular: dot={dot:.3f}"
            )


class TestWalkaroundClearance:
    """Tests for clearance during walkaround routing."""

    def test_j4_pad1_clearance(self, parser, hull_map):
        """
        Regression test: Route near J4 pad 1 maintains clearance.

        This tests the specific case where a route from U3:38 area
        passing near J4:1 was violating clearance due to incorrect
        vertex offset direction calculation.
        """
        # Find J4 pad 1
        j4_pad1 = None
        for pad in parser.pads:
            if pad.footprint_ref == 'J4' and pad.name == '1':
                j4_pad1 = pad
                break

        assert j4_pad1 is not None, "J4 pad 1 not found"

        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Route that passes near J4:1
        result = wr.route(
            Point(153.54, 98.01),
            Point(153.54, 94.10),
            net_id=57  # Different net from J4:1
        )

        assert result.success, "Route should succeed"
        assert len(result.path) > 0, "Path should have points"

        # Check all points maintain clearance
        trace_radius = 0.125
        required_clearance = 0.2  # Design rule clearance

        for i, p in enumerate(result.path):
            dist = GeometryChecker.point_to_pad_distance(p.x, p.y, j4_pad1)
            actual_clearance = dist - trace_radius

            assert actual_clearance >= required_clearance - 0.01, (
                f"Point {i} at ({p.x:.3f}, {p.y:.3f}) violates clearance: "
                f"actual={actual_clearance:.3f}mm, required={required_clearance}mm"
            )

    def test_route_around_rotated_pad_all_directions(self, parser, hull_map):
        """
        Test routing around a rotated pad from all directions.

        Routes should maintain clearance regardless of approach angle.
        """
        # Find J4 pad 1 (rotated roundrect)
        j4_pad1 = None
        for pad in parser.pads:
            if pad.footprint_ref == 'J4' and pad.name == '1':
                j4_pad1 = pad
                break

        assert j4_pad1 is not None

        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=0.25,
            max_iterations=1000,
            corner_offset=0.1
        )

        # Test routes from different directions
        test_routes = [
            # (start, end, description)
            (Point(150, 95.5), Point(158, 95.5), "left to right"),
            (Point(158, 95.5), Point(150, 95.5), "right to left"),
            (Point(154.6, 100), Point(154.6, 92), "top to bottom"),
            (Point(154.6, 92), Point(154.6, 100), "bottom to top"),
            (Point(150, 100), Point(158, 92), "diagonal NW to SE"),
            (Point(158, 92), Point(150, 100), "diagonal SE to NW"),
        ]

        trace_radius = 0.125
        required_clearance = 0.2

        for start, end, desc in test_routes:
            result = wr.route(start, end, net_id=999)  # Different net

            if not result.success:
                continue  # Some routes may not be possible

            # Check clearance
            for i, p in enumerate(result.path):
                dist = GeometryChecker.point_to_pad_distance(p.x, p.y, j4_pad1)
                actual_clearance = dist - trace_radius

                assert actual_clearance >= required_clearance - 0.02, (
                    f"Route '{desc}' point {i} at ({p.x:.3f}, {p.y:.3f}) "
                    f"violates clearance: {actual_clearance:.3f}mm"
                )


class TestWalkaroundOffsetMagnitude:
    """Tests for offset magnitude calculation."""

    def test_offset_magnitude_includes_trace_width(self, hull_map):
        """
        Verify offset includes half trace width plus corner offset.
        """
        trace_width = 0.25
        corner_offset = 0.1

        wr = WalkaroundRouter(
            hull_map=hull_map,
            trace_width=trace_width,
            max_iterations=100,
            corner_offset=corner_offset
        )

        expected_offset = trace_width / 2 + corner_offset
        assert abs(wr.half_width - trace_width / 2) < 0.001
        assert abs(wr.corner_offset - corner_offset) < 0.001

        # Create a simple horizontal edge
        hull = LineChain(points=[
            Point(0, 0),
            Point(1, 0),
            Point(1, 1),
            Point(0, 1),
        ])

        # Offset from midpoint of bottom edge
        midpoint = Point(0.5, 0)
        offset_point = wr._offset_from_hull(midpoint, hull, 0)

        # Offset should be exactly expected_offset in Y direction (down)
        offset_dist = (offset_point - midpoint).length()
        assert abs(offset_dist - expected_offset) < 0.001, (
            f"Offset magnitude {offset_dist:.3f} != expected {expected_offset:.3f}"
        )
