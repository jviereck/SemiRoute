"""Pytest configuration for SemiRouter tests."""
import pickle
import pytest
from pathlib import Path

from backend.pcb import PCBParser
from backend.routing import TraceRouter, ObstacleMap


# Cache directory for pickled fixtures
CACHE_DIR = Path(__file__).parent / ".test_cache"
PCB_FILE = Path(__file__).parent.parent / "BLDriver.kicad_pcb"


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (run with -m slow or skip with -m 'not slow')"
    )


def _get_cache_path(name: str) -> Path:
    """Get path for a cached pickle file."""
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{name}.pkl"


def _is_cache_valid(cache_path: Path) -> bool:
    """Check if cache file exists and is newer than the PCB file."""
    if not cache_path.exists():
        return False
    # Invalidate if PCB file is newer than cache
    return cache_path.stat().st_mtime > PCB_FILE.stat().st_mtime


def _load_or_build(cache_path: Path, builder):
    """Load from cache or build and save."""
    if _is_cache_valid(cache_path):
        try:
            with open(cache_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # Rebuild on any error

    # Build fresh
    obj = builder()

    # Save to cache
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(obj, f)
    except Exception:
        pass  # Don't fail if we can't cache

    return obj


@pytest.fixture(scope="session")
def parser():
    """Load the test PCB file (cached for entire test session)."""
    cache_path = _get_cache_path("parser")
    return _load_or_build(cache_path, lambda: PCBParser(PCB_FILE))


@pytest.fixture(scope="session")
def cached_obstacle_map_fcu(parser):
    """Create a cached obstacle map for F.Cu layer with pre-expanded cells."""
    cache_path = _get_cache_path("obstacle_map_fcu_v2")

    # Check if we can load from cache
    if _is_cache_valid(cache_path):
        try:
            with open(cache_path, "rb") as f:
                obs_map = pickle.load(f)
                obs_map.parser = parser
                return obs_map
        except Exception:
            pass

    # Build fresh
    obs_map = ObstacleMap(parser, layer="F.Cu", clearance=0.2)

    # Pre-expand for common trace radii (0.125mm for 0.25mm trace)
    obs_map.get_expanded_blocked(0.125)

    # Save to cache
    try:
        obs_map.parser = None
        with open(cache_path, "wb") as f:
            pickle.dump(obs_map, f)
        obs_map.parser = parser
    except Exception:
        obs_map.parser = parser

    return obs_map


@pytest.fixture(scope="session")
def cached_router(parser):
    """Create a router with cached obstacle maps and pre-expanded cells."""
    cache_path = _get_cache_path("router_obstacles_v2")

    # Check if we can load obstacle cache from pickle
    obstacle_cache = None
    if _is_cache_valid(cache_path):
        try:
            with open(cache_path, "rb") as f:
                obstacle_cache = pickle.load(f)
                for obs_map in obstacle_cache.values():
                    obs_map.parser = parser
        except Exception:
            obstacle_cache = None

    # Create router
    router = TraceRouter(parser, clearance=0.2, cache_obstacles=False)

    if obstacle_cache:
        router._obstacle_cache = obstacle_cache
    else:
        # Build fresh
        router._build_obstacle_cache()

        # Pre-expand for common trace radii (saves ~10s per search)
        for obs_map in router._obstacle_cache.values():
            obs_map.get_expanded_blocked(0.125)  # For 0.25mm trace

        # Save to pickle
        try:
            for obs_map in router._obstacle_cache.values():
                obs_map.parser = None
            with open(cache_path, "wb") as f:
                pickle.dump(router._obstacle_cache, f)
            for obs_map in router._obstacle_cache.values():
                obs_map.parser = parser
        except Exception:
            for obs_map in router._obstacle_cache.values():
                obs_map.parser = parser

    return router
