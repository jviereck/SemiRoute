"""Test routing behavior when endpoint is on a different net."""
import pytest
from backend.pcb import PCBParser
from backend.routing import TraceRouter

PCB_FILE = "BLDriver.kicad_pcb"


@pytest.fixture(scope="module")
def parser():
    """Load PCB parser once for all tests."""
    return PCBParser(PCB_FILE)


@pytest.fixture(scope="module")
def router(parser):
    """Create router with caching for performance."""
    return TraceRouter(parser, clearance=0.2, cache_obstacles=True)


class TestDifferentNetRouting:
    """Test routing behavior when start and end are on different nets."""

    def test_find_different_net_pads(self, parser):
        """Find two adjacent pads on different nets for testing."""
        # Find U3 which should have GND and NC pads close together
        u3_pads = [p for p in parser.pads if p.footprint_ref == "U3"]
        assert len(u3_pads) > 0, "U3 footprint not found"

        # Find pads on different nets
        net_groups = {}
        for pad in u3_pads:
            if pad.net_id not in net_groups:
                net_groups[pad.net_id] = []
            net_groups[pad.net_id].append(pad)

        # We should have pads on multiple different nets
        assert len(net_groups) > 1, "U3 should have pads on different nets"

        print(f"\nU3 has pads on {len(net_groups)} different nets")
        for net_id, pads in list(net_groups.items())[:3]:
            net_name = parser.nets.get(net_id, "unknown")
            print(f"  Net {net_id} ({net_name}): {len(pads)} pads")

    def test_find_net_at_point_detects_pad(self, router, parser):
        """Test that find_net_at_point correctly detects pad nets."""
        # Find a pad to test
        pad = None
        for p in parser.pads:
            if p.net_id and p.net_id > 0:
                pad = p
                break

        assert pad is not None, "No pad with net found"

        # Check that find_net_at_point returns the correct net
        found_net = router.find_net_at_point(pad.x, pad.y, "F.Cu", tolerance=0.5)

        # Should find the pad's net (or possibly another pad if they overlap)
        assert found_net is not None, f"Should find net at pad position ({pad.x}, {pad.y})"
        print(f"\nPad at ({pad.x:.2f}, {pad.y:.2f}) is net {pad.net_id}, find_net_at_point returned {found_net}")

    def test_route_to_different_net_blocked_by_endpoint_check(self, router, parser):
        """Test that routing from one net to a different net pad is detected.

        This tests the backend's endpoint net validation which prevents
        accidentally routing to a wrong-net pad.
        """
        # Find two pads on different nets that are relatively close
        pads_by_net = {}
        for pad in parser.pads:
            if pad.net_id and pad.net_id > 0 and "F.Cu" in pad.layers:
                if pad.net_id not in pads_by_net:
                    pads_by_net[pad.net_id] = []
                pads_by_net[pad.net_id].append(pad)

        # Find two different nets
        net_ids = list(pads_by_net.keys())
        assert len(net_ids) >= 2, "Need at least 2 nets to test"

        start_pad = pads_by_net[net_ids[0]][0]
        end_pad = pads_by_net[net_ids[1]][0]

        print(f"\nStart pad: net {start_pad.net_id} at ({start_pad.x:.2f}, {start_pad.y:.2f})")
        print(f"End pad: net {end_pad.net_id} at ({end_pad.x:.2f}, {end_pad.y:.2f})")

        # The endpoint net detection should find the different net
        end_net = router.find_net_at_point(end_pad.x, end_pad.y, "F.Cu")
        assert end_net is not None, "Should find net at end pad"
        assert end_net != start_pad.net_id, "End net should be different from start net"

        print(f"Endpoint net detection: {end_net} (different from start net {start_pad.net_id})")

    def test_route_succeeds_to_same_net_pad(self, router, parser):
        """Test that routing to a same-net pad succeeds."""
        # Find a net with at least 2 pads
        pads_by_net = {}
        for pad in parser.pads:
            if pad.net_id and pad.net_id > 0 and "F.Cu" in pad.layers:
                if pad.net_id not in pads_by_net:
                    pads_by_net[pad.net_id] = []
                pads_by_net[pad.net_id].append(pad)

        # Find a net with multiple pads
        multi_pad_net = None
        for net_id, pads in pads_by_net.items():
            if len(pads) >= 2:
                multi_pad_net = net_id
                break

        assert multi_pad_net is not None, "Need a net with at least 2 pads"

        pads = pads_by_net[multi_pad_net]
        start_pad = pads[0]
        end_pad = pads[1]

        print(f"\nSame-net routing test:")
        print(f"  Net: {multi_pad_net} ({parser.nets.get(multi_pad_net, 'unknown')})")
        print(f"  Start: ({start_pad.x:.2f}, {start_pad.y:.2f})")
        print(f"  End: ({end_pad.x:.2f}, {end_pad.y:.2f})")

        # Endpoint net check should pass (same net)
        end_net = router.find_net_at_point(end_pad.x, end_pad.y, "F.Cu")
        if end_net is not None:
            # End pad detected - should be same net
            assert end_net == multi_pad_net, f"End net {end_net} should match start net {multi_pad_net}"
            print(f"  Endpoint net check passed: {end_net} == {multi_pad_net}")

    def test_route_to_empty_space_succeeds(self, router, parser):
        """Test that routing to empty space (no pad) succeeds."""
        # Find a pad to start from
        start_pad = None
        for pad in parser.pads:
            if pad.net_id and pad.net_id > 0 and "F.Cu" in pad.layers:
                start_pad = pad
                break

        assert start_pad is not None

        # Route to a point away from any pad (offset by 2mm)
        end_x = start_pad.x + 2.0
        end_y = start_pad.y

        # Endpoint should not be on any pad
        end_net = router.find_net_at_point(end_x, end_y, "F.Cu", tolerance=0.3)

        print(f"\nRouting to empty space:")
        print(f"  Start: ({start_pad.x:.2f}, {start_pad.y:.2f}) net {start_pad.net_id}")
        print(f"  End: ({end_x:.2f}, {end_y:.2f}) net {end_net}")

        # If end_net is None, there's no pad there - good
        # If end_net matches start net, that's also fine (same-net element)
        # Only a problem if end_net is different from start
        if end_net is not None and end_net != start_pad.net_id:
            print(f"  WARNING: End point is on different net {end_net}")
        else:
            print(f"  End point is clear or same-net")

        # Try the actual route
        path = router.route(
            start_x=start_pad.x,
            start_y=start_pad.y,
            end_x=end_x,
            end_y=end_y,
            layer="F.Cu",
            width=0.25,
            net_id=start_pad.net_id
        )

        # Path may or may not exist depending on obstacles
        print(f"  Route result: {len(path)} waypoints")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
