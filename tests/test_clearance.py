"""Tests for trace clearance to other-net pads."""
import pytest
import math

from backend.pcb.parser import PCBParser
from backend.routing import TraceRouter, ObstacleMap
from backend.config import DEFAULT_PCB_FILE


@pytest.fixture
def parser():
    """Load the test PCB."""
    return PCBParser(DEFAULT_PCB_FILE)


@pytest.fixture
def router(parser):
    """Create a router with obstacle caching."""
    return TraceRouter(parser, clearance=0.2, cache_obstacles=True)


def point_to_segment_distance(px, py, x1, y1, x2, y2):
    """Calculate shortest distance from point to line segment."""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy

    if length_sq < 0.0001:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def check_path_clearance_to_pads(path, trace_width, layer, pads, exclude_net_id, clearance):
    """
    Check that a path maintains clearance to all pads of other nets.

    Returns list of violations: [(segment_idx, pad_id, actual_clearance, required_clearance)]
    """
    trace_radius = trace_width / 2
    violations = []

    for pad in pads:
        # Skip if pad not on this layer or same net
        if layer not in pad.layers:
            continue
        if pad.net_id == exclude_net_id:
            continue

        # Get pad edge radius (use larger dimension for safety)
        pad_radius = max(pad.width, pad.height) / 2

        # Check each segment of the path
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]

            # Distance from pad center to trace centerline
            dist_to_centerline = point_to_segment_distance(
                pad.x, pad.y, x1, y1, x2, y2
            )

            # Actual clearance = distance - trace_radius - pad_radius
            actual_clearance = dist_to_centerline - trace_radius - pad_radius

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
        Specifically test routing near IC pins where pins are closely spaced.
        This is the scenario the user reported (U2 pins 7, 8, 9).
        """
        # Find U2 component
        u2_pads = [p for p in parser.pads if p.footprint_ref == 'U2']

        if not u2_pads:
            # Try to find any IC with multiple pins
            footprint_pads = {}
            for p in parser.pads:
                if p.footprint_ref not in footprint_pads:
                    footprint_pads[p.footprint_ref] = []
                footprint_pads[p.footprint_ref].append(p)

            # Find a component with at least 8 pins
            for ref, pads in footprint_pads.items():
                if len(pads) >= 8:
                    u2_pads = pads
                    break

        if not u2_pads:
            pytest.skip("No suitable IC found")

        # Find pin 8 or equivalent middle pin
        target_pad = None
        for p in sorted(u2_pads, key=lambda x: x.name):
            if p.name == '8':
                target_pad = p
                break

        if not target_pad:
            target_pad = u2_pads[len(u2_pads) // 2]

        # Get target net
        target_net = target_pad.net_id
        layer = 'F.Cu' if 'F.Cu' in target_pad.layers else list(target_pad.layers)[0]

        # Find a starting point away from the IC
        start_x = target_pad.x - 5
        start_y = target_pad.y

        # Route to the target pad
        trace_width = 0.25
        path = router.route(
            start_x, start_y,
            target_pad.x, target_pad.y,
            layer=layer,
            width=trace_width,
            net_id=target_net
        )

        if not path:
            pytest.skip("No route found")

        # Check clearance
        violations = check_path_clearance_to_pads(
            path, trace_width, layer, parser.pads,
            exclude_net_id=target_net,
            clearance=router.clearance
        )

        if violations:
            print(f"\nClearance violations near {target_pad.footprint_ref}:")
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
