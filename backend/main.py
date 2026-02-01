"""FastAPI application for PCB viewer."""
from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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
            message="No valid route found - path may be blocked"
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
                "segment_count": len(t.segments)
            }
            for t in traces
        ]
    }


# Mount static files last (after API routes)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
