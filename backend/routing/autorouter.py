"""Auto-router for finding multi-layer routes with automatic via placement."""
from typing import Optional
from dataclasses import dataclass

from .router import TraceRouter


@dataclass
class AutoRouteSegment:
    """A single segment of an auto-routed path."""
    path: list[tuple[float, float]]
    layer: str


@dataclass
class AutoRouteVia:
    """A via placed during auto-routing."""
    x: float
    y: float
    size: float


@dataclass
class AutoRouteResult:
    """Result of an auto-routing attempt."""
    success: bool
    segments: list[AutoRouteSegment]
    vias: list[AutoRouteVia]
    message: str = ""


class AutoRouter:
    """
    Auto-router that finds paths with automatic via placement.

    Uses a cascading strategy:
    1. Try preferred layer first
    2. Try alternate layers if blocked
    3. Try single via routing (via candidates along direct path)
    4. Try double via routing for complex obstacles
    """

    # Copper layers to try
    COPPER_LAYERS = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]

    def __init__(
        self,
        trace_router: TraceRouter,
        via_size: float = 0.8,
        via_drill: float = 0.4
    ):
        """
        Initialize the auto-router.

        Args:
            trace_router: The underlying trace router for pathfinding
            via_size: Default via outer diameter (mm)
            via_drill: Default via drill size (mm)
        """
        self.trace_router = trace_router
        self.via_size = via_size
        self.via_drill = via_drill

    def auto_route(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        preferred_layer: str,
        width: float,
        net_id: Optional[int] = None,
        via_size: Optional[float] = None,
        max_vias: int = 2
    ) -> AutoRouteResult:
        """
        Automatically route between two points, placing vias if needed.

        Args:
            start_x, start_y: Start position (mm)
            end_x, end_y: End position (mm)
            preferred_layer: Preferred copper layer to start routing on
            width: Trace width (mm)
            net_id: Optional net ID for same-net crossing
            via_size: Via outer diameter (mm), defaults to instance default
            max_vias: Maximum number of vias to place (1 or 2)

        Returns:
            AutoRouteResult with success status, segments, vias, and message
        """
        if via_size is None:
            via_size = self.via_size

        # Strategy 1: Try preferred layer only
        result = self._try_single_layer(
            start_x, start_y, end_x, end_y, preferred_layer, width, net_id
        )
        if result.success:
            return result

        # Strategy 2: Try alternate layers
        for layer in self.COPPER_LAYERS:
            if layer == preferred_layer:
                continue
            result = self._try_single_layer(
                start_x, start_y, end_x, end_y, layer, width, net_id
            )
            if result.success:
                return result

        # Strategy 3: Try single via routing
        via_candidates = self._generate_via_candidates(start_x, start_y, end_x, end_y)

        for via_x, via_y in via_candidates:
            # Try via from preferred layer to each alternate layer
            for alt_layer in self.COPPER_LAYERS:
                if alt_layer == preferred_layer:
                    continue

                result = self._try_with_via(
                    start_x, start_y, end_x, end_y,
                    via_x, via_y,
                    preferred_layer, alt_layer,
                    width, net_id, via_size
                )
                if result.success:
                    return result

        # Strategy 4: Try double via routing (more complex paths)
        if max_vias >= 2:
            for via1_x, via1_y in via_candidates:
                for via2_x, via2_y in via_candidates:
                    if via1_x == via2_x and via1_y == via2_y:
                        continue

                    for mid_layer in self.COPPER_LAYERS:
                        if mid_layer == preferred_layer:
                            continue

                        result = self._try_with_double_via(
                            start_x, start_y, end_x, end_y,
                            via1_x, via1_y, via2_x, via2_y,
                            preferred_layer, mid_layer,
                            width, net_id, via_size
                        )
                        if result.success:
                            return result

        return AutoRouteResult(
            success=False,
            segments=[],
            vias=[],
            message="No valid route found - all paths blocked"
        )

    def _try_single_layer(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        layer: str,
        width: float,
        net_id: Optional[int]
    ) -> AutoRouteResult:
        """Attempt to route on a single layer without vias."""
        path = self.trace_router.route(
            start_x, start_y, end_x, end_y,
            layer=layer,
            width=width,
            net_id=net_id
        )

        if path:
            return AutoRouteResult(
                success=True,
                segments=[AutoRouteSegment(path=path, layer=layer)],
                vias=[],
                message=f"Route found on {layer}"
            )

        return AutoRouteResult(
            success=False,
            segments=[],
            vias=[],
            message=f"No route on {layer}"
        )

    def _try_with_via(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        via_x: float,
        via_y: float,
        layer1: str,
        layer2: str,
        width: float,
        net_id: Optional[int],
        via_size: float
    ) -> AutoRouteResult:
        """Attempt to route with a single via between two layers."""
        # First check if via placement is valid
        via_radius = via_size / 2
        valid, msg = self.trace_router.check_via_placement(
            via_x, via_y, via_radius, net_id
        )
        if not valid:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Via blocked: {msg}"
            )

        # Try routing start -> via on layer1
        path1 = self.trace_router.route(
            start_x, start_y, via_x, via_y,
            layer=layer1,
            width=width,
            net_id=net_id
        )
        if not path1:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Cannot route to via on {layer1}"
            )

        # Try routing via -> end on layer2
        path2 = self.trace_router.route(
            via_x, via_y, end_x, end_y,
            layer=layer2,
            width=width,
            net_id=net_id
        )
        if not path2:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Cannot route from via on {layer2}"
            )

        return AutoRouteResult(
            success=True,
            segments=[
                AutoRouteSegment(path=path1, layer=layer1),
                AutoRouteSegment(path=path2, layer=layer2)
            ],
            vias=[AutoRouteVia(x=via_x, y=via_y, size=via_size)],
            message=f"Route found with via: {layer1} -> {layer2}"
        )

    def _try_with_double_via(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        via1_x: float,
        via1_y: float,
        via2_x: float,
        via2_y: float,
        start_layer: str,
        mid_layer: str,
        width: float,
        net_id: Optional[int],
        via_size: float
    ) -> AutoRouteResult:
        """Attempt to route with two vias (start_layer -> mid_layer -> start_layer)."""
        via_radius = via_size / 2

        # Check both vias are valid
        valid1, msg1 = self.trace_router.check_via_placement(
            via1_x, via1_y, via_radius, net_id
        )
        if not valid1:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Via 1 blocked: {msg1}"
            )

        valid2, msg2 = self.trace_router.check_via_placement(
            via2_x, via2_y, via_radius, net_id
        )
        if not valid2:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Via 2 blocked: {msg2}"
            )

        # Route start -> via1 on start_layer
        path1 = self.trace_router.route(
            start_x, start_y, via1_x, via1_y,
            layer=start_layer,
            width=width,
            net_id=net_id
        )
        if not path1:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Cannot route to via1 on {start_layer}"
            )

        # Route via1 -> via2 on mid_layer
        path2 = self.trace_router.route(
            via1_x, via1_y, via2_x, via2_y,
            layer=mid_layer,
            width=width,
            net_id=net_id
        )
        if not path2:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Cannot route between vias on {mid_layer}"
            )

        # Route via2 -> end on start_layer
        path3 = self.trace_router.route(
            via2_x, via2_y, end_x, end_y,
            layer=start_layer,
            width=width,
            net_id=net_id
        )
        if not path3:
            return AutoRouteResult(
                success=False,
                segments=[],
                vias=[],
                message=f"Cannot route from via2 on {start_layer}"
            )

        return AutoRouteResult(
            success=True,
            segments=[
                AutoRouteSegment(path=path1, layer=start_layer),
                AutoRouteSegment(path=path2, layer=mid_layer),
                AutoRouteSegment(path=path3, layer=start_layer)
            ],
            vias=[
                AutoRouteVia(x=via1_x, y=via1_y, size=via_size),
                AutoRouteVia(x=via2_x, y=via2_y, size=via_size)
            ],
            message=f"Route found with 2 vias: {start_layer} -> {mid_layer} -> {start_layer}"
        )

    def _generate_via_candidates(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float
    ) -> list[tuple[float, float]]:
        """
        Generate candidate positions for via placement.

        Returns points along the direct path at 25%, 50%, 75%,
        plus points offset perpendicular to the path.
        """
        candidates = []

        dx = end_x - start_x
        dy = end_y - start_y
        length = (dx * dx + dy * dy) ** 0.5

        if length < 0.001:
            # Start and end are same point
            return [(start_x, start_y)]

        # Points along the direct path
        for t in [0.25, 0.5, 0.75]:
            x = start_x + t * dx
            y = start_y + t * dy
            candidates.append((x, y))

        # Perpendicular offset distance (1mm or 10% of length, whichever is larger)
        offset = max(1.0, length * 0.1)

        # Unit perpendicular vector
        perp_x = -dy / length
        perp_y = dx / length

        # Add offset points at 50% along path
        mid_x = start_x + 0.5 * dx
        mid_y = start_y + 0.5 * dy
        candidates.append((mid_x + offset * perp_x, mid_y + offset * perp_y))
        candidates.append((mid_x - offset * perp_x, mid_y - offset * perp_y))

        # Add offset points at 25% and 75%
        for t in [0.25, 0.75]:
            px = start_x + t * dx
            py = start_y + t * dy
            candidates.append((px + offset * perp_x, py + offset * perp_y))
            candidates.append((px - offset * perp_x, py - offset * perp_y))

        return candidates
