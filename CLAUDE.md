# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SemiRouter is a PCB viewer and interactive trace router for KiCad PCB files. It provides a web-based interface for visualizing PCB layouts, highlighting nets, and interactively routing new traces using A* pathfinding.

## Commands

### Run the server
```bash
uvicorn backend.main:app --reload
```
The server serves both the API and frontend.

**Important:** Do not start uvicorn with a fixed port (e.g., `--port 8000`). The port is determined by the git branch name.

### Run tests
```bash
# All tests
npm test

# Specific test suites (Puppeteer browser tests)
npm run test:click
npm run test:traces
npm run test:c5
npm run test:trace-mode
npm run test:routing
npm run test:multilayer
npm run test:selection
npm run test:highlight

# Python unit tests (pytest)
pytest tests/
pytest tests/test_routing.py -v
pytest tests/test_routing.py::TestTraceRouter::test_route_between_points -v

# Skip slow A* routing tests
pytest tests/ -m "not slow"
```

## Architecture

### Backend (Python/FastAPI)

**Entry point:** `backend/main.py` - FastAPI app with routing endpoints

**Core modules:**
- `backend/pcb/parser.py` - Parses KiCad `.kicad_pcb` files using `kiutils` library. Extracts footprints, pads, traces, vias, and graphics organized by layer.
- `backend/pcb/models.py` - Dataclasses for PCB elements (PadInfo, TraceInfo, ViaInfo, etc.)
- `backend/svg/generator.py` - Generates SVG from parsed PCB data with per-layer groups and clearance visualization
- `backend/routing/router.py` - TraceRouter class using A* pathfinding with 8-direction movement
- `backend/routing/obstacles.py` - ObstacleMap builds blocked cell grid from pads/traces/vias with clearance inflation
- `backend/routing/pending.py` - PendingTraceStore tracks user-created traces for clearance checking

**Key API endpoints:**
- `GET /api/svg` - Returns SVG of the PCB (optional `layers` query param)
- `GET /api/pcb/info` - Board metadata (bounds, counts)
- `POST /api/route` - A* routing between two points
- `POST /api/check-via` - Validates via placement across all copper layers
- `POST /api/traces` - Registers user trace for clearance checking
- `DELETE /api/traces/{id}` - Removes a user trace

### Frontend (Vanilla JS)

**Entry point:** `frontend/index.html` + `frontend/js/main.js`

**Key components:**
- `frontend/js/svg-viewer.js` - SVG pan/zoom, layer visibility, net highlighting
- `frontend/js/main.js` - App state, trace mode, routing session management

**Trace mode workflow:**
1. First click on pad sets start point (detects layer and net from clicked element)
2. Mouse move triggers debounced A* routing requests (50ms debounce)
3. Single click commits segment, clicked point becomes new start
4. Keys 1-4 place via and switch to corresponding layer (F.Cu, B.Cu, In1.Cu, In2.Cu)
5. Double-click or Confirm button ends routing session
6. Escape cancels session and removes all uncommitted traces

### Tests

- Python tests in `tests/` use pytest with fixtures in `conftest.py`
- Browser tests in `tests/test_*.js` use Puppeteer
- Slow A* integration tests are marked with `@pytest.mark.slow`
- Test fixtures cache parsed PCB and obstacle maps with pickle for faster startup

## Design Patterns

**Net-aware routing:** The router allows traces to cross same-net elements (pads, traces, vias) by passing `net_id` to route requests. ObstacleMap filters blocked cells by `allowed_net_id`.

**Obstacle caching:** TraceRouter pre-builds obstacle maps for all copper layers at startup (`cache_obstacles=True`). For same-net routing, it computes allowed cells dynamically.

**Pending trace store:** User-created traces are stored in `PendingTraceStore` and included as `extra_blocked` cells in A* queries, ensuring new routes avoid previously routed traces.

**Coordinate systems:**
- PCB coordinates are in millimeters
- Grid resolution is 0.025mm (configurable)
- Default clearance is 0.2mm
