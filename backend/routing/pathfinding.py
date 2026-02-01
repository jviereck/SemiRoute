"""A* pathfinding for PCB routing with 8-direction movement."""
import heapq
import math

import numpy as np
from scipy import ndimage

from typing import Optional
from .obstacles import ObstacleMap, ElementAwareMap
from .geometry import GeometryChecker


# 8 directions: N, NE, E, SE, S, SW, W, NW (0°, 45°, 90°, etc.)
DIRECTIONS = (
    (0, -1),   # N (0°)
    (1, -1),   # NE (45°)
    (1, 0),    # E (90°)
    (1, 1),    # SE (135°)
    (0, 1),    # S (180°)
    (-1, 1),   # SW (225°)
    (-1, 0),   # W (270°)
    (-1, -1),  # NW (315°)
)

# Costs: orthogonal = 1.0, diagonal = sqrt(2)
SQRT2 = math.sqrt(2)
DIRECTION_COSTS = (1.0, SQRT2, 1.0, SQRT2, 1.0, SQRT2, 1.0, SQRT2)

# Penalties for direction changes based on angle difference
# Index diff 0 = same direction (no turn)
# Index diff 1 = 45° turn (slight bend)
# Index diff 2 = 90° turn (sharp corner)
# Index diff 3 = 135° turn (very sharp)
# Index diff 4 = 180° turn (U-turn, should be avoided)
# Note: Direction indices wrap around (8 directions)
TURN_PENALTIES = {
    0: 0.0,    # No turn - free
    1: 0.1,    # 45° turn - small penalty (preferred bends)
    2: 0.5,    # 90° turn - moderate penalty
    3: 1.5,    # 135° turn - high penalty (avoid)
    4: 3.0,    # 180° turn - very high penalty (almost never)
}

# Heuristic weight for weighted A* (>1 = faster but less optimal)
HEURISTIC_WEIGHT = 1.5


def _expand_cells_fast(
    cells: set[tuple[int, int]],
    radius: float,
    resolution: float
) -> set[tuple[int, int]]:
    """
    Expand a set of cells by a radius using fast numpy-based dilation.

    Args:
        cells: Set of grid cells to expand
        radius: Expansion radius in world units (mm)
        resolution: Grid cell size (mm)

    Returns:
        Expanded set of cells
    """
    if not cells or radius <= 0:
        return cells

    grid_radius = int(math.ceil(radius / resolution))
    if grid_radius == 0:
        return cells

    # Get bounds
    min_gx = min(c[0] for c in cells)
    max_gx = max(c[0] for c in cells)
    min_gy = min(c[1] for c in cells)
    max_gy = max(c[1] for c in cells)

    # Add padding for expansion
    pad = grid_radius + 1
    width = max_gx - min_gx + 1 + 2 * pad
    height = max_gy - min_gy + 1 + 2 * pad

    # Create numpy array
    cell_array = np.zeros((height, width), dtype=np.uint8)
    for gx, gy in cells:
        cell_array[gy - min_gy + pad, gx - min_gx + pad] = 1

    # Create circular structuring element
    y, x = np.ogrid[-grid_radius:grid_radius + 1,
                    -grid_radius:grid_radius + 1]
    structuring_element = (x * x + y * y <= grid_radius * grid_radius).astype(np.uint8)

    # Dilate
    dilated = ndimage.binary_dilation(cell_array, structure=structuring_element)

    # Convert back to set
    expanded: set[tuple[int, int]] = set()
    gy_indices, gx_indices = np.where(dilated)
    for gy_idx, gx_idx in zip(gy_indices, gx_indices):
        gx = gx_idx + min_gx - pad
        gy = gy_idx + min_gy - pad
        expanded.add((gx, gy))

    return expanded


def heuristic(x1: int, y1: int, x2: int, y2: int) -> float:
    """Octile distance heuristic (optimal for 8-direction movement)."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    return max(dx, dy) + (SQRT2 - 1) * min(dx, dy)


def astar_search(
    obstacle_map: ObstacleMap,
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    trace_radius: float = 0,
    allowed_cells: set[tuple[int, int]] | None = None,
    extra_blocked: set[tuple[int, int]] | None = None
) -> list[tuple[float, float]]:
    """
    Find shortest path using weighted A* algorithm with 8-direction movement.

    Optimizations:
    - Uses tuples instead of objects for nodes
    - Direct access to blocked set
    - Bounded search area
    - Weighted heuristic for faster convergence

    Args:
        obstacle_map: Map of blocked areas
        start_x, start_y: Start position (world coordinates)
        end_x, end_y: End position (world coordinates)
        trace_radius: Half of trace width for collision checking
        allowed_cells: Optional set of cells that are allowed even if blocked
                      (used for same-net routing)
        extra_blocked: Optional set of additional blocked cells
                      (used for pending user traces)

    Returns:
        List of (x, y) waypoints in world coordinates, or empty list if no path
    """
    resolution = obstacle_map.resolution
    allowed = allowed_cells or set()
    extra = extra_blocked or set()

    # Get blocked cells (expanded by trace radius if needed)
    # Uses cached expansion from obstacle map for speed
    # Also expand allowed cells to match, so same-net routing works correctly
    if trace_radius > 0:
        blocked = obstacle_map.get_expanded_blocked(trace_radius)
        extra = _expand_cells_fast(extra, trace_radius, resolution) if extra else set()
        allowed = _expand_cells_fast(allowed, trace_radius, resolution) if allowed else set()
    else:
        blocked = obstacle_map._blocked

    # Convert to grid coordinates
    start_gx = int(round(start_x / resolution))
    start_gy = int(round(start_y / resolution))
    end_gx = int(round(end_x / resolution))
    end_gy = int(round(end_y / resolution))

    # Get board bounds
    min_gx, min_gy, max_gx, max_gy = obstacle_map.get_bounds()

    # A* data structures
    # open_set entries: (f_score, g_score, x, y, direction)
    open_set: list[tuple[float, float, int, int, int]] = []
    closed_set: set[tuple[int, int]] = set()
    g_scores: dict[tuple[int, int], float] = {}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}

    # Initialize
    start_h = heuristic(start_gx, start_gy, end_gx, end_gy)
    heapq.heappush(open_set, (start_h * HEURISTIC_WEIGHT, 0.0, start_gx, start_gy, -1))
    g_scores[(start_gx, start_gy)] = 0.0

    # Search
    iterations = 0
    max_iterations = 100000

    while open_set and iterations < max_iterations:
        iterations += 1

        _, g, cx, cy, c_dir = heapq.heappop(open_set)
        pos = (cx, cy)

        # Goal check
        if cx == end_gx and cy == end_gy:
            return _reconstruct_path(came_from, pos, (start_gx, start_gy), resolution)

        # Skip if already processed
        if pos in closed_set:
            continue
        closed_set.add(pos)

        # Expand neighbors
        for dir_idx in range(8):
            dx, dy = DIRECTIONS[dir_idx]
            nx, ny = cx + dx, cy + dy

            # Bounds check
            if not (min_gx <= nx <= max_gx and min_gy <= ny <= max_gy):
                continue

            npos = (nx, ny)

            # Skip if already processed
            if npos in closed_set:
                continue

            # Check if blocked (unless it's the goal or in allowed set)
            is_goal = (nx == end_gx and ny == end_gy)
            is_blocked = (npos in blocked or npos in extra) and npos not in allowed
            if not is_goal and is_blocked:
                continue

            # For diagonal moves, check corners to prevent cutting through
            if dx != 0 and dy != 0:
                c1 = (cx + dx, cy)
                c2 = (cx, cy + dy)
                c1_blocked = (c1 in blocked or c1 in extra) and c1 not in allowed
                c2_blocked = (c2 in blocked or c2 in extra) and c2 not in allowed
                if c1_blocked or c2_blocked:
                    continue

            # Calculate cost
            move_cost = DIRECTION_COSTS[dir_idx]
            if c_dir >= 0 and c_dir != dir_idx:
                # Calculate turn angle (minimum distance in direction indices)
                # e.g., from N(0) to E(2) = 2 steps, from N(0) to NW(7) = 1 step
                dir_diff = abs(dir_idx - c_dir)
                if dir_diff > 4:
                    dir_diff = 8 - dir_diff  # Wrap around
                move_cost += TURN_PENALTIES.get(dir_diff, 0.5)

            new_g = g + move_cost

            # Check if this is a better path
            old_g = g_scores.get(npos)
            if old_g is not None and old_g <= new_g:
                continue

            g_scores[npos] = new_g
            came_from[npos] = pos

            h = heuristic(nx, ny, end_gx, end_gy)
            new_f = new_g + h * HEURISTIC_WEIGHT
            heapq.heappush(open_set, (new_f, new_g, nx, ny, dir_idx))

    # No path found
    return []


def _reconstruct_path(
    came_from: dict[tuple[int, int], tuple[int, int]],
    end: tuple[int, int],
    start: tuple[int, int],
    resolution: float
) -> list[tuple[float, float]]:
    """Reconstruct and simplify path from A* result."""
    # Build raw path
    raw_path: list[tuple[int, int]] = []
    pos = end
    while pos != start:
        raw_path.append(pos)
        pos = came_from[pos]
    raw_path.append(start)
    raw_path.reverse()

    # Simplify: remove collinear points
    if len(raw_path) < 3:
        return [(x * resolution, y * resolution) for x, y in raw_path]

    simplified: list[tuple[int, int]] = [raw_path[0]]

    for i in range(1, len(raw_path) - 1):
        prev = simplified[-1]
        curr = raw_path[i]
        next_pt = raw_path[i + 1]

        # Check if direction changes
        dx1, dy1 = curr[0] - prev[0], curr[1] - prev[1]
        dx2, dy2 = next_pt[0] - curr[0], next_pt[1] - curr[1]

        # Normalize to unit direction
        if dx1 != 0:
            dx1 = dx1 // abs(dx1)
        if dy1 != 0:
            dy1 = dy1 // abs(dy1)
        if dx2 != 0:
            dx2 = dx2 // abs(dx2)
        if dy2 != 0:
            dy2 = dy2 // abs(dy2)

        # If direction changes, keep this point
        if dx1 != dx2 or dy1 != dy2:
            simplified.append(curr)

    simplified.append(raw_path[-1])

    # Convert to world coordinates
    return [(x * resolution, y * resolution) for x, y in simplified]


def astar_search_element_aware(
    obstacle_map: ElementAwareMap,
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    trace_radius: float = 0,
    net_id: Optional[int] = None,
    pending_traces: Optional[list] = None
) -> list[tuple[float, float]]:
    """
    A* pathfinding using element-aware obstacle checking.

    Key differences from astar_search:
    - No allowed_cells/extra_blocked complexity
    - Checks actual geometry at each cell
    - Net filtering is done during is_blocked check

    Args:
        obstacle_map: ElementAwareMap with spatial index
        start_x, start_y: Start position (world coordinates)
        end_x, end_y: End position (world coordinates)
        trace_radius: Half of trace width for collision checking
        net_id: Net ID for same-net routing (passed to is_blocked)
        pending_traces: Optional list of pending traces to also avoid

    Returns:
        List of (x, y) waypoints, or empty list if no path found
    """
    resolution = obstacle_map.resolution

    # Convert to grid coordinates
    start_gx = int(round(start_x / resolution))
    start_gy = int(round(start_y / resolution))
    end_gx = int(round(end_x / resolution))
    end_gy = int(round(end_y / resolution))

    # Get board bounds
    min_gx, min_gy, max_gx, max_gy = obstacle_map.get_bounds()

    # A* data structures
    open_set: list[tuple[float, float, int, int, int]] = []
    closed_set: set[tuple[int, int]] = set()
    g_scores: dict[tuple[int, int], float] = {}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}

    # Initialize
    start_h = heuristic(start_gx, start_gy, end_gx, end_gy)
    heapq.heappush(open_set, (start_h * HEURISTIC_WEIGHT, 0.0, start_gx, start_gy, -1))
    g_scores[(start_gx, start_gy)] = 0.0

    iterations = 0
    max_iterations = 100000

    while open_set and iterations < max_iterations:
        iterations += 1

        _, g, cx, cy, c_dir = heapq.heappop(open_set)
        pos = (cx, cy)

        if cx == end_gx and cy == end_gy:
            return _reconstruct_path(came_from, pos, (start_gx, start_gy), resolution)

        if pos in closed_set:
            continue
        closed_set.add(pos)

        for dir_idx in range(8):
            dx, dy = DIRECTIONS[dir_idx]
            nx, ny = cx + dx, cy + dy

            if not (min_gx <= nx <= max_gx and min_gy <= ny <= max_gy):
                continue

            npos = (nx, ny)
            if npos in closed_set:
                continue

            # Convert to world coordinates for geometry check
            world_x = nx * resolution
            world_y = ny * resolution

            # Check if blocked using element-aware method
            is_goal = (nx == end_gx and ny == end_gy)
            is_blocked = obstacle_map.is_blocked(world_x, world_y, trace_radius, net_id)

            # Also check pending traces
            if pending_traces and not is_blocked:
                for pending in pending_traces:
                    if _point_blocked_by_pending(
                        world_x, world_y, trace_radius,
                        pending, obstacle_map.clearance, net_id
                    ):
                        is_blocked = True
                        break

            if not is_goal and is_blocked:
                continue

            # Corner cutting check for diagonal moves
            if dx != 0 and dy != 0:
                c1_x, c1_y = cx + dx, cy
                c2_x, c2_y = cx, cy + dy
                c1_world_x, c1_world_y = c1_x * resolution, c1_y * resolution
                c2_world_x, c2_world_y = c2_x * resolution, c2_y * resolution

                c1_blocked = obstacle_map.is_blocked(c1_world_x, c1_world_y, trace_radius, net_id)
                c2_blocked = obstacle_map.is_blocked(c2_world_x, c2_world_y, trace_radius, net_id)

                # Also check pending for corners
                if pending_traces:
                    if not c1_blocked:
                        for pending in pending_traces:
                            if _point_blocked_by_pending(
                                c1_world_x, c1_world_y, trace_radius,
                                pending, obstacle_map.clearance, net_id
                            ):
                                c1_blocked = True
                                break
                    if not c2_blocked:
                        for pending in pending_traces:
                            if _point_blocked_by_pending(
                                c2_world_x, c2_world_y, trace_radius,
                                pending, obstacle_map.clearance, net_id
                            ):
                                c2_blocked = True
                                break

                if c1_blocked or c2_blocked:
                    continue

            # Calculate cost (same as before)
            move_cost = DIRECTION_COSTS[dir_idx]
            if c_dir >= 0 and c_dir != dir_idx:
                dir_diff = abs(dir_idx - c_dir)
                if dir_diff > 4:
                    dir_diff = 8 - dir_diff
                move_cost += TURN_PENALTIES.get(dir_diff, 0.5)

            new_g = g + move_cost

            old_g = g_scores.get(npos)
            if old_g is not None and old_g <= new_g:
                continue

            g_scores[npos] = new_g
            came_from[npos] = pos

            h = heuristic(nx, ny, end_gx, end_gy)
            new_f = new_g + h * HEURISTIC_WEIGHT
            heapq.heappush(open_set, (new_f, new_g, nx, ny, dir_idx))

    return []


def _point_blocked_by_pending(
    x: float, y: float, trace_radius: float,
    pending, clearance: float,
    net_id: Optional[int]
) -> bool:
    """Check if point is blocked by a pending trace."""
    # Skip same-net pending traces
    if net_id is not None and pending.net_id == net_id:
        return False

    required_clearance = clearance + trace_radius + pending.width / 2

    segments = pending.segments
    for i in range(len(segments) - 1):
        dist = GeometryChecker._point_to_segment(
            x, y,
            segments[i][0], segments[i][1],
            segments[i + 1][0], segments[i + 1][1]
        )
        if dist < required_clearance:
            return True

    return False
