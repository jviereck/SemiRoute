# Trace Routing Mode Implementation Plan

## Overview

Add a "trace mode" to SemiRouter that allows users to interactively route traces between points on the PCB. The feature will:
1. Remember a starting point when clicking on a pad, via, or trace
2. Route a trace to the next clicked point using shortest-path routing
3. Respect clearances to all obstacles (pads, traces, vias, cutouts)
4. Allow layer selection for the new trace

## Design Decisions

### Clearance Handling
The KiCad PCB file (`BLDriver.kicad_pcb`) has minimal clearance info. KiCad 9.0+ stores design rules in separate `.kicad_dru` files. We will:
- Use a configurable default clearance (0.2mm, matching `DEFAULT_CLEARANCE` in generator.py)
- Attempt to parse `.kicad_dru` file if present alongside the PCB file
- Allow user override via UI

### Routing Algorithm
Use A* pathfinding with:
- Grid-based navigation (configurable resolution, default 0.1mm)
- Obstacle map built from pads, traces, vias, and edge cuts
- Clearance inflation around all obstacles
- 45-degree routing preference (standard PCB practice)

### Trace Storage
New traces will be stored in memory (not persisted to KiCad file initially). They will:
- Be rendered in the SVG like existing traces
- Be part of the same highlight/selection system
- Have a visual indicator that they're "pending" (dashed outline)

---

## Implementation Steps

### Phase 1: Frontend - Trace Mode UI

**File: `frontend/index.html`**
- Add trace mode toggle button in sidebar
- Add layer selection dropdown for new traces
- Add trace width input field
- Add status indicator showing current mode state

**File: `frontend/js/main.js`**
- Add `appMode` state variable ('select' | 'trace')
- Add `traceStartPoint` to store first click coordinates
- Add `selectedLayer` and `traceWidth` state
- Modify click handler to be mode-aware:
  - In 'select' mode: existing behavior (net highlighting)
  - In 'trace' mode: first click sets start, second click triggers routing
- Add keyboard shortcut 'T' to toggle trace mode
- Add visual feedback for start point selection

**File: `frontend/js/svg-viewer.js`**
- Add `showStartMarker(x, y)` method to display start point indicator
- Add `renderPendingTrace(points)` method for preview
- Add `clearPendingElements()` to remove temporary graphics

**File: `frontend/css/styles.css`**
- Add styles for trace mode UI elements
- Add styles for start point marker (pulsing indicator)
- Add styles for pending trace (dashed line)

### Phase 2: Backend - Routing Module

**New File: `backend/routing/__init__.py`**
```python
from .router import TraceRouter
from .obstacles import ObstacleMap
```

**New File: `backend/routing/obstacles.py`**
- `ObstacleMap` class:
  - Build grid from PCB dimensions
  - Mark cells occupied by pads (with clearance inflation)
  - Mark cells occupied by traces (with clearance inflation)
  - Mark cells occupied by vias (with clearance inflation)
  - Mark cells outside edge cuts as blocked
  - Method: `is_blocked(x, y, clearance) -> bool`
  - Method: `get_neighbors(x, y) -> list[tuple[float, float]]`

**New File: `backend/routing/router.py`**
- `TraceRouter` class:
  - Constructor takes PCBParser and clearance settings
  - Method: `route(start_x, start_y, end_x, end_y, layer, width) -> list[tuple[float, float]]`
  - Uses A* algorithm with 8-direction movement (orthogonal + diagonal)
  - Returns list of waypoints for the trace path
  - Simplifies path to remove redundant collinear points

**New File: `backend/routing/pathfinding.py`**
- A* implementation optimized for PCB routing:
  - Heuristic: Euclidean distance
  - Cost: Actual distance traveled + penalty for direction changes
  - 45-degree angle preference
  - Early termination when target reached

### Phase 3: Backend - API Endpoints

**File: `backend/api/routes.py`**
- Add new endpoint `POST /api/route`:
  ```python
  @app.post("/api/route")
  async def route_trace(request: RouteRequest):
      # RouteRequest: start_x, start_y, end_x, end_y, layer, width, clearance
      # Returns: list of points forming the trace path
  ```
- Add endpoint `GET /api/design-rules`:
  - Returns default clearances and trace widths
  - Attempts to parse .kicad_dru if present

**New File: `backend/api/models.py`** (or add to existing)
- `RouteRequest` Pydantic model
- `RouteResponse` Pydantic model with path points

### Phase 4: Integration

**File: `backend/svg/generator.py`**
- Add method `add_pending_trace(points, layer, width)` for rendering user traces
- Pending traces rendered with distinct styling (dashed, different opacity)

**File: `frontend/js/main.js`**
- Wire up routing API call on second click
- Display routed trace as preview
- Add "confirm" / "cancel" buttons for pending traces
- Handle routing failures with user feedback

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `frontend/index.html` | Modify | Add trace mode UI panel |
| `frontend/js/main.js` | Modify | Add mode state and routing logic |
| `frontend/js/svg-viewer.js` | Modify | Add marker and preview methods |
| `frontend/css/styles.css` | Modify | Add trace mode styles |
| `backend/routing/__init__.py` | New | Routing module init |
| `backend/routing/obstacles.py` | New | Obstacle map builder |
| `backend/routing/router.py` | New | A* router implementation |
| `backend/routing/pathfinding.py` | New | Pathfinding algorithm |
| `backend/api/routes.py` | Modify | Add routing endpoint |
| `backend/svg/generator.py` | Modify | Add pending trace rendering |

---

## Testing Strategy

1. **Unit tests** for obstacle map building
2. **Unit tests** for A* pathfinding with known obstacle layouts
3. **Integration tests** for routing API endpoint
4. **Puppeteer tests** for trace mode UI interaction

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Large PCBs may have slow routing | Use coarse grid initially, refine only near obstacles |
| No path exists between points | Return error with clear message, suggest layer change |
| Clearance data not in PCB file | Use sensible defaults, allow user override |

---

## Future Enhancements (Out of Scope)

- Multi-segment traces with intermediate waypoints
- Via insertion for layer changes
- Trace editing and deletion
- Save traces back to KiCad file format
- Design rule checking (DRC) for existing traces
