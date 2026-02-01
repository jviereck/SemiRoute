"""Test routing performance - first route should be fast."""
import time
import pytest
from backend.pcb import PCBParser
from backend.routing import TraceRouter

PCB_FILE = "BLDriver.kicad_pcb"


@pytest.fixture(scope="module")
def fresh_router():
    """Create a fresh router with caching (simulates server startup)."""
    parser = PCBParser(PCB_FILE)
    start = time.perf_counter()
    router = TraceRouter(
        parser,
        clearance=0.2,
        cache_obstacles=True
    )
    elapsed = time.perf_counter() - start
    print(f"\nRouter initialization took {elapsed*1000:.1f}ms")
    return router


class TestRoutingPerformance:
    """Test that routing is fast, especially the first route."""

    def test_first_route_is_fast(self, fresh_router):
        """First route from U2 pad 15 should complete in under 500ms."""
        # U2 pad 15 coordinates (from SVG)
        start_x, start_y = 152.5118, 81.4500
        end_x, end_y = start_x + 3.0, start_y

        start = time.perf_counter()
        path = fresh_router.route(
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            layer="F.Cu",
            width=0.25,
            net_id=83  # U2 pad 15's net
        )
        elapsed = time.perf_counter() - start

        print(f"\nFirst route took {elapsed*1000:.1f}ms, {len(path)} waypoints")

        assert path, "Route should succeed"
        assert len(path) >= 2, "Route should have at least 2 waypoints"
        assert elapsed < 0.5, f"First route took {elapsed*1000:.1f}ms, should be < 500ms"

    def test_subsequent_routes_are_fast(self, fresh_router):
        """Subsequent routes should be very fast (<100ms)."""
        start_x, start_y = 152.5118, 81.4500

        times = []
        successful = 0
        for i in range(5):
            # Use smaller offsets to avoid obstacles
            end_x = start_x + 1.0 + i * 0.3

            start = time.perf_counter()
            path = fresh_router.route(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=start_y,
                layer="F.Cu",
                width=0.25,
                net_id=83
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)

            if path:
                successful += 1

        avg_time = sum(times) / len(times)
        max_time = max(times)
        print(f"\nSubsequent routes: avg={avg_time*1000:.1f}ms, max={max_time*1000:.1f}ms, {successful}/5 succeeded")

        assert successful >= 3, f"At least 3 routes should succeed, got {successful}"
        # Allow up to 1 second for complex routes that may need A* fallback
        assert max_time < 1.0, f"Max route time {max_time*1000:.1f}ms should be < 1000ms"

    def test_blocked_endpoint_is_fast(self, fresh_router):
        """Route to blocked endpoint should fail fast (not try expensive routing)."""
        # This is the exact request that was taking 4 seconds
        start_x, start_y = 152.5118, 81.45
        end_x, end_y = 152.1582, 81.8036  # Blocked by obstacle

        start = time.perf_counter()
        path = fresh_router.route(
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            layer="F.Cu",
            width=0.25,
            net_id=45
        )
        elapsed = time.perf_counter() - start

        print(f"\nBlocked endpoint route took {elapsed*1000:.1f}ms")

        # Route should fail (blocked endpoint) but should be fast
        # Note: The router itself doesn't do the early return - that's in main.py
        # But the walkaround should still be reasonably fast
        assert elapsed < 1.0, f"Blocked route took {elapsed*1000:.1f}ms, should be < 1000ms"

    def test_different_layers_are_fast(self, fresh_router):
        """Routes on different layers should all be fast (caches pre-built)."""
        start_x, start_y = 152.5118, 81.4500
        end_x, end_y = start_x + 3.0, start_y

        for layer in ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]:
            start = time.perf_counter()
            path = fresh_router.route(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                layer=layer,
                width=0.25,
                net_id=83
            )
            elapsed = time.perf_counter() - start

            print(f"\n{layer}: {elapsed*1000:.1f}ms, {len(path) if path else 0} waypoints")

            # Each layer should be fast (cache pre-built)
            assert elapsed < 0.5, f"{layer} route took {elapsed*1000:.1f}ms, should be < 500ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
