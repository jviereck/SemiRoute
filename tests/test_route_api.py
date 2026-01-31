"""Test route API to diagnose timeout issue."""
import pytest
import signal
import time
from backend.pcb import PCBParser
from backend.routing import TraceRouter, ObstacleMap


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Test timed out!")


def with_timeout(seconds):
    """Decorator to add timeout to a function."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result
        return wrapper
    return decorator

PCB_FILE = "BLDriver.kicad_pcb"


@with_timeout(10)
def test_obstacle_map_creation():
    """Test that obstacle map can be created without hanging."""
    parser = PCBParser(PCB_FILE)

    start = time.time()
    obs_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)
    elapsed = time.time() - start

    print(f"\nObstacle map created in {elapsed:.2f}s")
    print(f"Blocked cells: {len(obs_map._blocked)}")
    assert elapsed < 30, f"Obstacle map creation took too long: {elapsed:.2f}s"


@with_timeout(10)
def test_router_creation():
    """Test that router can be created without hanging."""
    parser = PCBParser(PCB_FILE)

    start = time.time()
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=True)
    elapsed = time.time() - start

    print(f"\nRouter created in {elapsed:.2f}s")
    assert elapsed < 120, f"Router creation took too long: {elapsed:.2f}s"


@with_timeout(10)
def test_get_net_cells():
    """Test that _get_net_cells doesn't hang."""
    parser = PCBParser(PCB_FILE)
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=False)

    # Find GND net
    gnd_net_id = None
    for net_id, name in parser.nets.items():
        if name == "GND":
            gnd_net_id = net_id
            break

    assert gnd_net_id is not None

    start = time.time()
    allowed = router._get_net_cells("F.Cu", gnd_net_id)
    elapsed = time.time() - start

    print(f"\n_get_net_cells returned {len(allowed)} cells in {elapsed:.2f}s")
    assert elapsed < 10, f"_get_net_cells took too long: {elapsed:.2f}s"


@with_timeout(10)
def test_simple_route():
    """Test a simple route without net_id."""
    parser = PCBParser(PCB_FILE)
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=True)

    start = time.time()
    path = router.route(
        start_x=120.0, start_y=45.0,
        end_x=122.0, end_y=45.0,
        layer="F.Cu",
        width=0.25,
        net_id=None  # No net filtering
    )
    elapsed = time.time() - start

    print(f"\nRoute without net_id: {len(path)} points in {elapsed:.2f}s")
    assert elapsed < 30, f"Route took too long: {elapsed:.2f}s"


@with_timeout(10)
def test_route_with_net_id():
    """Test route with net_id (the problematic case)."""
    parser = PCBParser(PCB_FILE)
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=True)

    # Find GND net
    gnd_net_id = None
    for net_id, name in parser.nets.items():
        if name == "GND":
            gnd_net_id = net_id
            break

    print(f"\nGND net_id: {gnd_net_id}")

    start = time.time()
    path = router.route(
        start_x=120.0, start_y=45.0,
        end_x=122.0, end_y=45.0,
        layer="F.Cu",
        width=0.25,
        net_id=gnd_net_id
    )
    elapsed = time.time() - start

    print(f"Route with net_id: {len(path)} points in {elapsed:.2f}s")
    assert elapsed < 30, f"Route with net_id took too long: {elapsed:.2f}s"


def test_obstacle_map_bounds():
    """Check obstacle map size to understand performance."""
    parser = PCBParser(PCB_FILE)
    obs = ObstacleMap(parser, layer='F.Cu', clearance=0.2)

    min_gx = min(c[0] for c in obs._blocked)
    max_gx = max(c[0] for c in obs._blocked)
    min_gy = min(c[1] for c in obs._blocked)
    max_gy = max(c[1] for c in obs._blocked)

    print(f'\nGrid bounds: x=[{min_gx}, {max_gx}], y=[{min_gy}, {max_gy}]')
    print(f'Grid size: {max_gx - min_gx} x {max_gy - min_gy}')
    print(f'Blocked cells: {len(obs._blocked)}')
    print(f'Resolution: {obs.resolution}mm')
    print(f'World bounds: x=[{min_gx * obs.resolution:.1f}, {max_gx * obs.resolution:.1f}]mm')
    print(f'World bounds: y=[{min_gy * obs.resolution:.1f}, {max_gy * obs.resolution:.1f}]mm')

    # Calculate expansion cost
    trace_radius = 0.125  # 0.25mm trace
    grid_radius = int(trace_radius / obs.resolution) + 1
    expansion_ops = len(obs._blocked) * (2 * grid_radius + 1) ** 2
    print(f'\nExpansion grid radius: {grid_radius}')
    print(f'Expansion operations: {expansion_ops:,}')


if __name__ == "__main__":
    print("Testing obstacle map creation...")
    test_obstacle_map_creation()

    print("\nTesting obstacle map bounds...")
    test_obstacle_map_bounds()

    print("\nTesting _get_net_cells...")
    test_get_net_cells()

    print("\nTesting router creation...")
    test_router_creation()

    print("\nTesting simple route...")
    test_simple_route()

    print("\nTesting route with net_id...")
    test_route_with_net_id()

    print("\nAll tests passed!")
