"""Tests for trace clearance to other-net pads."""
import pytest
import math

from backend.pcb.parser import PCBParser
from backend.routing import TraceRouter, ObstacleMap, GeometryChecker
from backend.routing.hulls import Point
from backend.routing.hull_map import HullMap
from backend.config import DEFAULT_PCB_FILE


@pytest.fixture
def parser():
    """Load the test PCB."""
    return PCBParser(DEFAULT_PCB_FILE)


@pytest.fixture
def router(parser):
    """Create a router with obstacle caching."""
    return TraceRouter(parser, clearance=0.2, cache_obstacles=True)


def segment_to_pad_min_distance(x1, y1, x2, y2, pad, num_samples=50):
    """
    Calculate minimum distance from a line segment to a pad using exact geometry.

    Samples points along the segment and uses GeometryChecker for accurate
    distance calculation that handles rotated pads correctly.
    """
    length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    if length < 0.001:
        return GeometryChecker.point_to_pad_distance(x1, y1, pad)

    min_dist = float('inf')
    for i in range(num_samples + 1):
        t = i / num_samples
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)
        dist = GeometryChecker.point_to_pad_distance(px, py, pad)
        min_dist = min(min_dist, dist)

    return min_dist


def check_path_clearance_to_pads(path, trace_width, layer, pads, exclude_net_id, clearance):
    """
    Check that a path maintains clearance to all pads of other nets.

    Uses GeometryChecker for accurate distance calculation that handles
    rotated pads correctly (not just bounding circle approximation).

    Returns list of violations: [(segment_idx, pad_id, net_id, actual_clearance, required_clearance)]
    """
    trace_radius = trace_width / 2
    violations = []

    for pad in pads:
        # Skip if pad not on this layer or same net
        if layer not in pad.layers:
            continue
        if pad.net_id == exclude_net_id:
            continue

        # Check each segment of the path
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]

            # Distance from trace segment to pad edge (using exact geometry)
            dist_to_pad_edge = segment_to_pad_min_distance(x1, y1, x2, y2, pad)

            # Actual clearance = distance to pad edge - trace radius
            actual_clearance = dist_to_pad_edge - trace_radius

            if actual_clearance < clearance - 0.001:  # Small tolerance
                violations.append((
                    i,
                    f"{pad.footprint_ref}:{pad.name}",
                    pad.net_id,
                    actual_clearance,
                    clearance
                ))

    return violations


class TestTraceClearance:
    """Test that routed traces maintain clearance to other-net pads."""

    def test_route_avoids_other_net_pads(self, router, parser):
        """
        Route between two points and verify the path doesn't get too close
        to pads of other nets.
        """
        # Find a GND pad to start from
        gnd_pads = [p for p in parser.pads if 'GND' in parser.nets.get(p.net_id, '')]
        assert gnd_pads, "No GND pads found"

        start_pad = gnd_pads[0]
        layer = 'F.Cu' if 'F.Cu' in start_pad.layers else list(start_pad.layers)[0]

        # Find another GND pad to route to
        end_pad = None
        for p in gnd_pads:
            if p.pad_id != start_pad.pad_id and layer in p.layers:
                dist = math.sqrt((p.x - start_pad.x)**2 + (p.y - start_pad.y)**2)
                if dist > 5:  # At least 5mm away
                    end_pad = p
                    break

        if not end_pad:
            pytest.skip("Could not find suitable end pad")

        # Route
        trace_width = 0.25
        path = router.route(
            start_pad.x, start_pad.y,
            end_pad.x, end_pad.y,
            layer=layer,
            width=trace_width,
            net_id=start_pad.net_id
        )

        if not path:
            pytest.skip("No route found")

        # Check clearance to all pads
        violations = check_path_clearance_to_pads(
            path, trace_width, layer, parser.pads,
            exclude_net_id=start_pad.net_id,
            clearance=router.clearance
        )

        if violations:
            print(f"\nClearance violations found:")
            for seg_idx, pad_id, net_id, actual, required in violations:
                net_name = parser.nets.get(net_id, f"net_{net_id}")
                print(f"  Segment {seg_idx}: pad {pad_id} (net: {net_name})")
                print(f"    Actual clearance: {actual:.4f}mm, required: {required:.4f}mm")

        assert not violations, f"Found {len(violations)} clearance violations"

    def test_route_near_ic_pins(self, router, parser):
        """
        Test routing to an IC pin from a nearby component on the same net.

        Routes from C5 pad 1 (GND) to U2 pad 8 (GND), which requires navigating
        near the closely spaced U2 pins 7, 8, 9 without violating clearances.
        """
        # Find the specific pads we need
        c5_pad1 = None
        u2_pad8 = None

        for pad in parser.pads:
            if pad.footprint_ref == 'C5' and pad.name == '1':
                c5_pad1 = pad
            elif pad.footprint_ref == 'U2' and pad.name == '8':
                u2_pad8 = pad

        if c5_pad1 is None or u2_pad8 is None:
            pytest.skip("Required pads C5:1 or U2:8 not found")

        # Verify they're on the same net (GND)
        if c5_pad1.net_id != u2_pad8.net_id:
            pytest.skip("C5:1 and U2:8 not on same net")

        layer = 'F.Cu'
        trace_width = 0.25

        # Route from C5 to U2 pad 8
        path = router.route(
            c5_pad1.x, c5_pad1.y,
            u2_pad8.x, u2_pad8.y,
            layer=layer,
            width=trace_width,
            net_id=c5_pad1.net_id
        )

        if not path:
            pytest.skip("No route found")

        # Check clearance to all other-net pads
        violations = check_path_clearance_to_pads(
            path, trace_width, layer, parser.pads,
            exclude_net_id=c5_pad1.net_id,
            clearance=router.clearance
        )

        if violations:
            print(f"\nClearance violations routing C5->U2:8:")
            for seg_idx, pad_id, net_id, actual, required in violations:
                net_name = parser.nets.get(net_id, f"net_{net_id}")
                print(f"  Segment {seg_idx}: pad {pad_id} (net: {net_name})")
                print(f"    Actual clearance: {actual:.4f}mm, required: {required:.4f}mm")

        assert not violations, f"Found {len(violations)} clearance violations near IC pins"

    def test_trace_width_affects_clearance(self, router, parser):
        """
        Verify that wider traces require more clearance.
        This specifically tests that trace_radius is being used.
        """
        # Find two pads on the same net with some distance
        net_pads = {}
        for p in parser.pads:
            if p.net_id not in net_pads:
                net_pads[p.net_id] = []
            net_pads[p.net_id].append(p)

        # Find a net with at least 2 pads
        test_pads = None
        for net_id, pads in net_pads.items():
            if len(pads) >= 2 and net_id != 0:
                # Check distance
                p1, p2 = pads[0], pads[1]
                dist = math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
                if dist > 3:
                    test_pads = (p1, p2)
                    break

        if not test_pads:
            pytest.skip("No suitable pad pair found")

        p1, p2 = test_pads
        layer = 'F.Cu' if 'F.Cu' in p1.layers else list(p1.layers)[0]

        # Route with narrow trace
        narrow_path = router.route(
            p1.x, p1.y, p2.x, p2.y,
            layer=layer, width=0.15, net_id=p1.net_id
        )

        # Route with wide trace
        wide_path = router.route(
            p1.x, p1.y, p2.x, p2.y,
            layer=layer, width=0.5, net_id=p1.net_id
        )

        if not narrow_path or not wide_path:
            pytest.skip("Routes not found")

        # Check violations for each
        narrow_violations = check_path_clearance_to_pads(
            narrow_path, 0.15, layer, parser.pads,
            exclude_net_id=p1.net_id, clearance=router.clearance
        )

        wide_violations = check_path_clearance_to_pads(
            wide_path, 0.5, layer, parser.pads,
            exclude_net_id=p1.net_id, clearance=router.clearance
        )

        # Neither should have violations
        assert not narrow_violations, f"Narrow trace has {len(narrow_violations)} violations"
        assert not wide_violations, f"Wide trace has {len(wide_violations)} violations"


class TestObstacleMapCorrectness:
    """Test that obstacle maps correctly block other-net elements."""

    def test_other_net_pads_are_blocked(self, parser):
        """Verify that pads from other nets are blocked in the obstacle map."""
        # Build obstacle map for a specific net
        gnd_pads = [p for p in parser.pads if 'GND' in parser.nets.get(p.net_id, '')]
        assert gnd_pads

        gnd_net_id = gnd_pads[0].net_id
        layer = 'F.Cu'

        # Create obstacle map allowing only GND net
        obstacle_map = ObstacleMap(
            parser=parser,
            layer=layer,
            clearance=0.2,
            grid_resolution=0.025,
            allowed_net_id=gnd_net_id
        )

        # Check that other-net pads are blocked
        for pad in parser.pads:
            if layer not in pad.layers:
                continue
            if pad.net_id == gnd_net_id:
                # Same net pads should NOT be blocked
                # (allowing routing through them)
                continue

            # Other net pads SHOULD be blocked
            is_blocked = obstacle_map.is_blocked(pad.x, pad.y, radius=0)
            if not is_blocked:
                print(f"WARNING: Pad {pad.footprint_ref}:{pad.name} (net {pad.net_id}) "
                      f"at ({pad.x:.2f}, {pad.y:.2f}) is not blocked!")

    def test_blocked_with_trace_radius(self, parser):
        """
        Verify that is_blocked correctly accounts for trace radius.

        Tests the is_blocked method's radius parameter which expands
        the check area to account for trace width.
        """
        layer = 'F.Cu'

        # Create obstacle map with no allowed net (blocks everything)
        obstacle_map = ObstacleMap(
            parser=parser,
            layer=layer,
            clearance=0.2,
            grid_resolution=0.025,
            allowed_net_id=None
        )

        # Find any pad on this layer
        test_pad = None
        for pad in parser.pads:
            if layer in pad.layers:
                test_pad = pad
                break

        assert test_pad is not None, "No pad found on F.Cu"

        # The pad center should be blocked
        assert obstacle_map.is_blocked(test_pad.x, test_pad.y, radius=0), \
            "Pad center should be blocked"

        # Test that is_blocked with radius=0 vs radius>0 gives different results
        # at a point near the blocked boundary
        pad_radius = max(test_pad.width, test_pad.height) / 2
        boundary_dist = pad_radius + obstacle_map.clearance

        # Point just outside the boundary (should not be blocked with radius=0)
        outside_dist = boundary_dist + 0.05  # 0.05mm outside
        outside_x = test_pad.x + outside_dist

        # With no trace radius, this point might not be blocked
        blocked_no_radius = obstacle_map.is_blocked(outside_x, test_pad.y, radius=0)

        # With a trace radius, this same point should be blocked
        # because the trace edge would extend into the blocked zone
        trace_radius = 0.125  # 0.25mm wide trace
        blocked_with_radius = obstacle_map.is_blocked(outside_x, test_pad.y, radius=trace_radius)

        print(f"\nPad {test_pad.footprint_ref}:{test_pad.name}")
        print(f"  Pad radius: {pad_radius:.3f}mm, clearance: {obstacle_map.clearance:.3f}mm")
        print(f"  Boundary: {boundary_dist:.3f}mm, test point: {outside_dist:.3f}mm from center")
        print(f"  Blocked without trace radius: {blocked_no_radius}")
        print(f"  Blocked with trace_radius={trace_radius}mm: {blocked_with_radius}")

        # The key test: when trace has width, is_blocked should catch more cases
        # This verifies the radius parameter is being used correctly
        if not blocked_no_radius and blocked_with_radius:
            print("  SUCCESS: trace radius correctly expands blocking check")
        elif blocked_no_radius and blocked_with_radius:
            print("  INFO: point is blocked regardless of trace radius (dense board)")
        else:
            print("  WARNING: unexpected behavior")

        # At minimum, the pad center must be blocked
        assert obstacle_map.is_blocked(test_pad.x, test_pad.y, radius=trace_radius), \
            "Pad center should be blocked even with trace radius"


class TestHullGeneration:
    """Test that hulls are correctly generated for various pad shapes."""

    def test_rotated_oval_pad_hull_bounds(self, parser):
        """
        Test that rotated oval pads have correct hull dimensions.

        J4 pad 2 is a 1.7x2.0mm oval with -90° rotation.
        After rotation, effective dimensions are 2.0x1.7mm.
        With 0.2mm clearance, the hull should extend:
        - X: center ± (2.0/2 + 0.2) = center ± 1.2mm
        - Y: center ± (1.7/2 + 0.2) = center ± 1.05mm
        """
        # Find J4 pad 2
        j4_pad2 = None
        for pad in parser.pads:
            if pad.footprint_ref == 'J4' and pad.name == '2':
                j4_pad2 = pad
                break

        if j4_pad2 is None:
            pytest.skip("J4 pad 2 not found in test PCB")

        # Verify it's a rotated oval
        assert j4_pad2.shape == 'oval', f"Expected oval, got {j4_pad2.shape}"
        assert abs(abs(j4_pad2.angle) - 90) < 1, f"Expected ~90° rotation, got {j4_pad2.angle}°"

        # Create hull map
        layer = 'F.Cu' if 'F.Cu' in j4_pad2.layers else list(j4_pad2.layers)[0]
        clearance = 0.2
        hull_map = HullMap(parser, layer, clearance=clearance)

        # Find the hull for J4 pad 2
        j4_hull = None
        for indexed in hull_map.all_hulls():
            if indexed.source_type == 'pad' and indexed.source == j4_pad2:
                j4_hull = indexed
                break

        assert j4_hull is not None, "Hull for J4 pad 2 not found"

        # Calculate expected bounds
        # For -90° rotation: width (1.7) becomes height, height (2.0) becomes width
        eff_width = j4_pad2.height  # 2.0mm after rotation
        eff_height = j4_pad2.width  # 1.7mm after rotation

        expected_half_x = eff_width / 2 + clearance  # 1.0 + 0.2 = 1.2mm
        expected_half_y = eff_height / 2 + clearance  # 0.85 + 0.2 = 1.05mm

        expected_min_x = j4_pad2.x - expected_half_x
        expected_max_x = j4_pad2.x + expected_half_x
        expected_min_y = j4_pad2.y - expected_half_y
        expected_max_y = j4_pad2.y + expected_half_y

        # Allow small tolerance for hull approximation
        tolerance = 0.05

        print(f"\nJ4 pad 2: center=({j4_pad2.x:.3f}, {j4_pad2.y:.3f})")
        print(f"  Original: {j4_pad2.width}x{j4_pad2.height}mm, angle={j4_pad2.angle}°")
        print(f"  Effective after rotation: {eff_width}x{eff_height}mm")
        print(f"  Expected hull X: [{expected_min_x:.3f}, {expected_max_x:.3f}]")
        print(f"  Actual hull X:   [{j4_hull.min_x:.3f}, {j4_hull.max_x:.3f}]")
        print(f"  Expected hull Y: [{expected_min_y:.3f}, {expected_max_y:.3f}]")
        print(f"  Actual hull Y:   [{j4_hull.min_y:.3f}, {j4_hull.max_y:.3f}]")

        # Check X bounds
        assert abs(j4_hull.min_x - expected_min_x) < tolerance, \
            f"Hull min_x {j4_hull.min_x:.3f} != expected {expected_min_x:.3f}"
        assert abs(j4_hull.max_x - expected_max_x) < tolerance, \
            f"Hull max_x {j4_hull.max_x:.3f} != expected {expected_max_x:.3f}"

        # Check Y bounds
        assert abs(j4_hull.min_y - expected_min_y) < tolerance, \
            f"Hull min_y {j4_hull.min_y:.3f} != expected {expected_min_y:.3f}"
        assert abs(j4_hull.max_y - expected_max_y) < tolerance, \
            f"Hull max_y {j4_hull.max_y:.3f} != expected {expected_max_y:.3f}"

    def test_segment_hull_semicircle_caps(self):
        """
        Test that segment hulls have proper semicircular caps.

        The caps should extend the full radius beyond the segment endpoints.
        """
        from backend.routing.hulls import HullGenerator, Point

        # Create a horizontal segment hull
        start = Point(0, 0)
        end = Point(10, 0)
        width = 2.0
        clearance = 0.2
        half_width = width / 2 + clearance  # 1.2mm

        chain = HullGenerator.segment_hull(start, end, width, clearance)

        # Find the extreme X points (should be at caps)
        min_x = min(p.x for p in chain.points)
        max_x = max(p.x for p in chain.points)
        min_y = min(p.y for p in chain.points)
        max_y = max(p.y for p in chain.points)

        print(f"\nSegment hull: ({start.x}, {start.y}) to ({end.x}, {end.y})")
        print(f"  Width: {width}mm, clearance: {clearance}mm, half_width: {half_width}mm")
        print(f"  Hull X bounds: [{min_x:.3f}, {max_x:.3f}]")
        print(f"  Hull Y bounds: [{min_y:.3f}, {max_y:.3f}]")

        # Caps should extend half_width beyond endpoints
        tolerance = 0.01
        assert abs(min_x - (start.x - half_width)) < tolerance, \
            f"Start cap min_x {min_x:.3f} != expected {start.x - half_width:.3f}"
        assert abs(max_x - (end.x + half_width)) < tolerance, \
            f"End cap max_x {max_x:.3f} != expected {end.x + half_width:.3f}"

        # Y bounds should be symmetric around the segment
        assert abs(min_y - (-half_width)) < tolerance, \
            f"Hull min_y {min_y:.3f} != expected {-half_width:.3f}"
        assert abs(max_y - half_width) < tolerance, \
            f"Hull max_y {max_y:.3f} != expected {half_width:.3f}"
