"""FastAPI application for PCB viewer."""
import uuid

from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from kiutils.board import Board
from kiutils.items.brditems import Segment
from kiutils.items.common import Position
from pydantic import BaseModel
from typing import Optional

from .config import DEFAULT_PCB_FILE, DEFAULT_PORT, FRONTEND_DIR, PROJECT_ROOT
from .pcb import PCBParser
from .svg import SVGGenerator
from .routing import TraceRouter

app = FastAPI(title="SemiRouter PCB Viewer", version="0.1.0")


class RouteRequest(BaseModel):
    """Request model for trace routing."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    layer: str
    width: float
    net_id: Optional[int] = None
    skip_endpoint_check: bool = False  # Skip endpoint net validation


class RouteResponse(BaseModel):
    """Response model for trace routing."""
    success: bool
    path: list[list[float]]
    message: str = ""


class ViaCheckRequest(BaseModel):
    """Request model for via placement validation."""
    x: float
    y: float
    size: float = 0.8  # Default via outer diameter
    drill: float = 0.4  # Default drill size
    net_id: Optional[int] = None  # Net ID to allow crossing


class ViaCheckResponse(BaseModel):
    """Response model for via validation."""
    valid: bool
    message: str = ""


class TraceRequest(BaseModel):
    """Request model for registering a user trace."""
    id: str
    segments: list[list[float]]  # List of [x, y] points
    width: float
    layer: str
    net_id: Optional[int] = None


class TraceResponse(BaseModel):
    """Response model for trace operations."""
    success: bool
    message: str = ""


class TraceInfo(BaseModel):
    """Info model for a single trace."""
    id: str
    layer: str
    width: float
    net_id: Optional[int]
    segment_count: int

# Load PCB once at startup
pcb_parser = PCBParser(DEFAULT_PCB_FILE)
svg_generator = SVGGenerator(pcb_parser)

# Create router with cached obstacle maps at startup
# Traces are persisted to pending_traces.json in the project root
trace_router = TraceRouter(
    pcb_parser,
    clearance=0.2,
    cache_obstacles=True,
    pending_traces_file=PROJECT_ROOT / "pending_traces.json"
)

# Pre-expand blocked cells for common trace widths to avoid slow first request
# 0.125mm radius = 0.25mm trace width (most common)
for obs_map in trace_router._obstacle_cache.values():
    obs_map.get_expanded_blocked(0.125)


@app.get("/")
async def root():
    """Redirect to the frontend."""
    return RedirectResponse(url="/static/index.html")


@app.get("/api/svg")
async def get_svg(
    layers: str = Query(
        default=None,
        description="Comma-separated list of layers to include (default: all)"
    )
):
    """Generate and return SVG of the PCB."""
    layer_list = None
    if layers:
        layer_list = [l.strip() for l in layers.split(",") if l.strip()]
    svg_content = svg_generator.generate(layers=layer_list)
    return Response(content=svg_content, media_type="image/svg+xml")


@app.get("/api/pcb/info")
async def get_pcb_info():
    """Return PCB metadata."""
    info = pcb_parser.get_board_info()
    return {
        "bounds": {
            "min_x": info.min_x,
            "min_y": info.min_y,
            "max_x": info.max_x,
            "max_y": info.max_y,
            "width": info.width,
            "height": info.height,
        },
        "layers": info.layers,
        "counts": {
            "footprints": info.footprint_count,
            "pads": info.pad_count,
            "nets": info.net_count,
            "traces": info.trace_count,
            "vias": info.via_count,
        }
    }


@app.get("/api/nets")
async def get_nets():
    """Return list of all nets with pad counts."""
    nets = []
    for net_id, net_name in pcb_parser.nets.items():
        pads = pcb_parser.get_pads_by_net(net_id)
        nets.append({
            "id": net_id,
            "name": net_name,
            "pad_count": len(pads),
            "pads": [
                {"id": p.pad_id, "footprint": p.footprint_ref, "pad": p.name}
                for p in pads
            ]
        })
    return {"nets": sorted(nets, key=lambda n: n["id"])}


@app.get("/api/net/{net_id}")
async def get_net(net_id: int):
    """Return details for a specific net."""
    net_name = pcb_parser.nets.get(net_id, "")
    pads = pcb_parser.get_pads_by_net(net_id)
    return {
        "id": net_id,
        "name": net_name,
        "pads": [
            {
                "id": p.pad_id,
                "footprint": p.footprint_ref,
                "pad": p.name,
                "x": p.x,
                "y": p.y,
                "layers": p.layers,
            }
            for p in pads
        ]
    }


@app.post("/api/check-via", response_model=ViaCheckResponse)
async def check_via_placement(request: ViaCheckRequest):
    """
    Check if a via can be placed at the given coordinates.

    Vias span all copper layers, so we check clearance on each layer.
    Uses cached obstacle maps for fast response.
    """
    via_radius = request.size / 2
    valid, message = trace_router.check_via_placement(
        request.x, request.y, via_radius, request.net_id
    )
    return ViaCheckResponse(valid=valid, message=message)


@app.post("/api/route", response_model=RouteResponse)
async def route_trace(request: RouteRequest):
    """
    Route a trace between two points using A* pathfinding.

    The routing respects clearances to obstacles and only moves in
    0°, 45°, 90°, 135°, 180°, 225°, 270°, 315° directions.
    """
    # Try to find net ID at start point if not provided
    net_id = request.net_id
    if net_id is None:
        net_id = trace_router.find_net_at_point(
            request.start_x, request.start_y, request.layer
        )

    # Check if endpoint is on a different-net pad (prevent routing to wrong net)
    if not request.skip_endpoint_check:
        end_net_id = trace_router.find_net_at_point(
            request.end_x, request.end_y, request.layer
        )
        if end_net_id is not None and net_id is not None and end_net_id != net_id:
            end_net_name = pcb_parser.nets.get(end_net_id, f"Net {end_net_id}")
            start_net_name = pcb_parser.nets.get(net_id, f"Net {net_id}")
            return RouteResponse(
                success=False,
                path=[],
                message=f"Cannot route to different net: endpoint is on {end_net_name}, but routing from {start_net_name}"
            )

    # Check if start or end points are blocked - return early to avoid slow routing
    trace_radius = request.width / 2
    obs_map = trace_router.get_obstacle_map(request.layer, net_id)
    start_blocked = obs_map.is_blocked(request.start_x, request.start_y, trace_radius, net_id)
    end_blocked = obs_map.is_blocked(request.end_x, request.end_y, trace_radius, net_id) if not request.skip_endpoint_check else False

    # Return early if endpoints are blocked (avoid expensive routing attempt)
    if start_blocked or end_blocked:
        if start_blocked and end_blocked:
            msg = "Both start and end points are blocked"
        elif start_blocked:
            msg = "Start point is blocked (inside obstacle/clearance zone)"
        else:
            msg = "End point is blocked (inside obstacle/clearance zone)"
        return RouteResponse(success=False, path=[], message=msg)

    path = trace_router.route(
        start_x=request.start_x,
        start_y=request.start_y,
        end_x=request.end_x,
        end_y=request.end_y,
        layer=request.layer,
        width=request.width,
        net_id=net_id
    )

    if path:
        return RouteResponse(
            success=True,
            path=[[p[0], p[1]] for p in path],
            message=f"Route found with {len(path)} waypoints"
        )
    else:
        return RouteResponse(
            success=False,
            path=[],
            message="No valid route found - path may be blocked by obstacles"
        )


@app.post("/api/traces", response_model=TraceResponse)
async def register_trace(request: TraceRequest):
    """
    Register a new user-created trace for clearance checking.

    This adds the trace to the pending store so subsequent routing
    requests will avoid crossing it.
    """
    # Convert segments from list of [x, y] to list of (x, y) tuples
    segments = [(s[0], s[1]) for s in request.segments]

    trace_router.pending_store.add_trace(
        trace_id=request.id,
        segments=segments,
        width=request.width,
        layer=request.layer,
        net_id=request.net_id
    )

    return TraceResponse(
        success=True,
        message=f"Trace {request.id} registered on {request.layer}"
    )


@app.delete("/api/traces/{trace_id}", response_model=TraceResponse)
async def remove_trace(trace_id: str):
    """Remove a specific user trace from the pending store."""
    removed = trace_router.pending_store.remove_trace(trace_id)

    if removed:
        return TraceResponse(
            success=True,
            message=f"Trace {trace_id} removed"
        )
    else:
        return TraceResponse(
            success=False,
            message=f"Trace {trace_id} not found"
        )


@app.delete("/api/traces", response_model=TraceResponse)
async def clear_all_traces():
    """Remove all user traces from the pending store."""
    trace_router.pending_store.clear()

    return TraceResponse(
        success=True,
        message="All traces cleared"
    )


@app.get("/api/traces")
async def list_traces():
    """List all pending user traces."""
    traces = trace_router.pending_store.get_all_traces()

    return {
        "traces": [
            {
                "id": t.id,
                "layer": t.layer,
                "width": t.width,
                "net_id": t.net_id,
                "segments": [[p[0], p[1]] for p in t.segments]
            }
            for t in traces
        ]
    }


@app.get("/api/trace-path/{net_id}")
async def get_trace_path(
    net_id: int,
    layer: str = Query(..., description="Layer name (e.g., F.Cu)"),
    x: float = Query(..., description="Starting X coordinate"),
    y: float = Query(..., description="Starting Y coordinate")
):
    """
    Get connected trace path starting from a point.

    Reconstructs the trace path on the specified net/layer,
    starting from the nearest point to (x, y).
    """
    # Get all traces on this net and layer
    traces = [t for t in pcb_parser.get_traces_by_layer(layer) if t.net_id == net_id]

    if not traces:
        return {"success": False, "path": [], "width": 0.25, "message": "No traces found"}

    # Find the trace segment closest to the starting point
    best_trace = None
    best_dist = float('inf')

    for trace in traces:
        # Check distance to both endpoints
        dist_start = ((trace.start_x - x) ** 2 + (trace.start_y - y) ** 2) ** 0.5
        dist_end = ((trace.end_x - x) ** 2 + (trace.end_y - y) ** 2) ** 0.5
        min_dist = min(dist_start, dist_end)

        if min_dist < best_dist:
            best_dist = min_dist
            best_trace = trace

    if not best_trace:
        return {"success": False, "path": [], "width": 0.25, "message": "No trace found near point"}

    # Build connected path starting from best_trace
    path = []
    visited = set()
    width = best_trace.width

    def add_trace_to_path(trace, start_from_start=True):
        """Add trace segment to path, avoiding duplicates."""
        trace_id = id(trace)
        if trace_id in visited:
            return
        visited.add(trace_id)

        if start_from_start:
            if not path or (path[-1][0] != trace.start_x or path[-1][1] != trace.start_y):
                path.append([trace.start_x, trace.start_y])
            path.append([trace.end_x, trace.end_y])
        else:
            if not path or (path[-1][0] != trace.end_x or path[-1][1] != trace.end_y):
                path.append([trace.end_x, trace.end_y])
            path.append([trace.start_x, trace.start_y])

    def find_connected_traces(end_x, end_y, tolerance=0.01):
        """Find traces that connect to the given endpoint."""
        connected = []
        for trace in traces:
            if id(trace) in visited:
                continue
            # Check if trace starts or ends at this point
            if abs(trace.start_x - end_x) < tolerance and abs(trace.start_y - end_y) < tolerance:
                connected.append((trace, True))  # Start from start
            elif abs(trace.end_x - end_x) < tolerance and abs(trace.end_y - end_y) < tolerance:
                connected.append((trace, False))  # Start from end
        return connected

    # Start with the best trace
    add_trace_to_path(best_trace, True)

    # Walk forward from end
    current_x, current_y = best_trace.end_x, best_trace.end_y
    while True:
        connected = find_connected_traces(current_x, current_y)
        if not connected:
            break
        next_trace, from_start = connected[0]
        add_trace_to_path(next_trace, from_start)
        if from_start:
            current_x, current_y = next_trace.end_x, next_trace.end_y
        else:
            current_x, current_y = next_trace.start_x, next_trace.start_y

    # Walk backward from start (prepend to path)
    visited.clear()
    visited.add(id(best_trace))
    backward_path = []

    current_x, current_y = best_trace.start_x, best_trace.start_y
    while True:
        connected = find_connected_traces(current_x, current_y)
        if not connected:
            break
        next_trace, from_start = connected[0]
        visited.add(id(next_trace))
        if from_start:
            backward_path.insert(0, [next_trace.start_x, next_trace.start_y])
            current_x, current_y = next_trace.start_x, next_trace.start_y
            # Actually we need the other end
            backward_path.insert(0, [next_trace.end_x, next_trace.end_y])
            current_x, current_y = next_trace.end_x, next_trace.end_y
        else:
            backward_path.insert(0, [next_trace.end_x, next_trace.end_y])
            current_x, current_y = next_trace.end_x, next_trace.end_y
            backward_path.insert(0, [next_trace.start_x, next_trace.start_y])
            current_x, current_y = next_trace.start_x, next_trace.start_y

    # Combine backward and forward paths
    full_path = backward_path + path

    # Remove duplicate consecutive points
    cleaned_path = []
    for point in full_path:
        if not cleaned_path or cleaned_path[-1] != point:
            cleaned_path.append(point)

    return {
        "success": True,
        "path": cleaned_path,
        "width": width,
        "message": f"Found path with {len(cleaned_path)} points"
    }


@app.get("/api/export")
async def export_pcb():
    """Export PCB with user-routed traces as .kicad_pcb file."""
    # Load original board
    board = Board.from_file(str(DEFAULT_PCB_FILE))

    # Get all pending traces
    traces = trace_router.pending_store.get_all_traces()

    # Convert each trace to kiutils Segments
    for trace in traces:
        for i in range(len(trace.segments) - 1):
            x1, y1 = trace.segments[i]
            x2, y2 = trace.segments[i + 1]
            segment = Segment(
                start=Position(X=x1, Y=y1),
                end=Position(X=x2, Y=y2),
                width=trace.width,
                layer=trace.layer,
                net=trace.net_id or 0,
                tstamp=str(uuid.uuid4())
            )
            board.traceItems.append(segment)

    # Return as downloadable file
    content = board.to_sexpr(indent=0, newline=True)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=export.kicad_pcb"}
    )


# Mount static files last (after API routes)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
