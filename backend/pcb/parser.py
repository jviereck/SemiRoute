"""KiCad PCB file parser using kiutils."""
import math
from pathlib import Path
from typing import Union

from kiutils.board import Board

from .models import (
    BoardInfo, FootprintInfo, GraphicArc, GraphicLine,
    GraphicRect, GraphicCircle, GraphicPoly, PadInfo,
    TraceInfo, ViaInfo
)
from .transform import transform_pad_position, rotate_point

# Type alias for all graphic types
GraphicItem = Union[GraphicLine, GraphicArc, GraphicRect, GraphicCircle, GraphicPoly]


class PCBParser:
    """Parser for KiCad PCB files."""

    # Copper layers
    COPPER_LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

    # All renderable layers in order (back to front)
    ALL_LAYERS = [
        "B.CrtYd", "B.Fab", "B.SilkS",
        "Edge.Cuts",
        "B.Cu", "In2.Cu", "In1.Cu", "F.Cu",
        "F.SilkS", "F.Fab", "F.CrtYd",
    ]

    def __init__(self, pcb_path: str | Path):
        """Load and parse a KiCad PCB file."""
        self.pcb_path = Path(pcb_path)
        self.board = Board.from_file(str(self.pcb_path))

        # Build net lookup
        self._net_names: dict[int, str] = {}
        for net in self.board.nets:
            self._net_names[net.number] = net.name

        # Parse elements
        self._footprints: list[FootprintInfo] = []
        self._pads: list[PadInfo] = []
        self._graphics: dict[str, list[GraphicItem]] = {layer: [] for layer in self.ALL_LAYERS}
        self._net_to_pads: dict[int, list[PadInfo]] = {}
        self._traces: dict[str, list[TraceInfo]] = {layer: [] for layer in self.COPPER_LAYERS}
        self._vias: list[ViaInfo] = []

        self._parse_footprints()
        self._parse_board_graphics()
        self._parse_traces_and_vias()
        self._calculate_bounds()

    def _expand_layers(self, layers: list[str]) -> list[str]:
        """Expand wildcard layer patterns like *.Cu to actual layer names."""
        expanded = []
        for layer in layers:
            if layer == "*.Cu":
                # Expand to all copper layers
                expanded.extend(self.COPPER_LAYERS)
            elif layer.startswith("*."):
                # Other wildcards (e.g., *.Mask) - skip non-copper wildcards
                continue
            else:
                expanded.append(layer)
        return expanded

    def _parse_footprints(self) -> None:
        """Extract footprints and their pads."""
        for fp in self.board.footprints:
            # Get footprint properties
            fp_x = fp.position.X
            fp_y = fp.position.Y
            fp_angle = fp.position.angle or 0.0
            fp_layer = fp.layer

            # Get reference and value (properties is a dict in kiutils)
            reference = fp.properties.get("Reference", "")
            value = fp.properties.get("Value", "")

            fp_info = FootprintInfo(
                reference=reference,
                value=value,
                x=fp_x,
                y=fp_y,
                angle=fp_angle,
                layer=fp_layer,
                pads=[]
            )

            # Process pads
            for pad in fp.pads:
                pad_x = pad.position.X
                pad_y = pad.position.Y
                pad_angle = pad.position.angle or 0.0

                # Transform to absolute position
                abs_x, abs_y, total_angle = transform_pad_position(
                    pad_x, pad_y, pad_angle,
                    fp_x, fp_y, fp_angle
                )

                # Get pad size
                width = pad.size.X
                height = pad.size.Y

                # Get pad shape
                shape = pad.shape if pad.shape else "rect"

                # Get layers (expand wildcards like *.Cu)
                layers = self._expand_layers(list(pad.layers) if pad.layers else [])

                # Get net
                net_id = pad.net.number if pad.net else 0
                net_name = self._net_names.get(net_id, "")

                # Get roundrect ratio
                roundrect_ratio = 0.0
                if hasattr(pad, 'roundrectRatio') and pad.roundrectRatio:
                    roundrect_ratio = pad.roundrectRatio

                # Get drill size
                drill = None
                if pad.drill and pad.drill.diameter:
                    drill = pad.drill.diameter

                pad_info = PadInfo(
                    name=pad.number,
                    x=abs_x,
                    y=abs_y,
                    width=width,
                    height=height,
                    shape=shape,
                    angle=total_angle,
                    layers=layers,
                    net_id=net_id,
                    net_name=net_name,
                    footprint_ref=reference,
                    roundrect_ratio=roundrect_ratio,
                    drill=drill
                )

                fp_info.pads.append(pad_info)
                self._pads.append(pad_info)

                # Add to net mapping
                if net_id not in self._net_to_pads:
                    self._net_to_pads[net_id] = []
                self._net_to_pads[net_id].append(pad_info)

            # Parse footprint graphics
            self._parse_footprint_graphics(fp, fp_x, fp_y, fp_angle)

            self._footprints.append(fp_info)

    def _parse_footprint_graphics(self, fp, fp_x: float, fp_y: float, fp_angle: float) -> None:
        """Extract graphic elements from a footprint."""
        for item in fp.graphicItems:
            layer = getattr(item, 'layer', None)
            if not layer or layer not in self._graphics:
                continue

            # Get stroke width
            width = 0.12  # default
            if hasattr(item, 'stroke') and item.stroke:
                width = item.stroke.width or 0.12

            # Check for fill
            fill = False
            if hasattr(item, 'fill') and item.fill:
                fill = item.fill == 'solid' or item.fill == True

            item_type = type(item).__name__

            if item_type == 'FpLine':
                start_rx, start_ry = rotate_point(item.start.X, item.start.Y, -fp_angle)
                end_rx, end_ry = rotate_point(item.end.X, item.end.Y, -fp_angle)
                self._graphics[layer].append(GraphicLine(
                    start_x=fp_x + start_rx,
                    start_y=fp_y + start_ry,
                    end_x=fp_x + end_rx,
                    end_y=fp_y + end_ry,
                    width=width,
                    layer=layer
                ))

            elif item_type == 'FpRect':
                # Transform all four corners
                x1, y1 = item.start.X, item.start.Y
                x2, y2 = item.end.X, item.end.Y
                # Rotate corners
                c1 = rotate_point(x1, y1, -fp_angle)
                c2 = rotate_point(x2, y1, -fp_angle)
                c3 = rotate_point(x2, y2, -fp_angle)
                c4 = rotate_point(x1, y2, -fp_angle)
                # Translate to footprint position
                points = [
                    (fp_x + c1[0], fp_y + c1[1]),
                    (fp_x + c2[0], fp_y + c2[1]),
                    (fp_x + c3[0], fp_y + c3[1]),
                    (fp_x + c4[0], fp_y + c4[1]),
                ]
                self._graphics[layer].append(GraphicPoly(
                    points=points,
                    width=width,
                    layer=layer,
                    fill=fill
                ))

            elif item_type == 'FpCircle':
                center_rx, center_ry = rotate_point(item.center.X, item.center.Y, -fp_angle)
                # Calculate radius from center to end point
                radius = math.sqrt((item.end.X - item.center.X)**2 + (item.end.Y - item.center.Y)**2)
                self._graphics[layer].append(GraphicCircle(
                    center_x=fp_x + center_rx,
                    center_y=fp_y + center_ry,
                    radius=radius,
                    width=width,
                    layer=layer,
                    fill=fill
                ))

            elif item_type == 'FpArc':
                start_rx, start_ry = rotate_point(item.start.X, item.start.Y, -fp_angle)
                mid_rx, mid_ry = rotate_point(item.mid.X, item.mid.Y, -fp_angle) if item.mid else (start_rx, start_ry)
                end_rx, end_ry = rotate_point(item.end.X, item.end.Y, -fp_angle)
                self._graphics[layer].append(GraphicArc(
                    start_x=fp_x + start_rx,
                    start_y=fp_y + start_ry,
                    mid_x=fp_x + mid_rx,
                    mid_y=fp_y + mid_ry,
                    end_x=fp_x + end_rx,
                    end_y=fp_y + end_ry,
                    width=width,
                    layer=layer
                ))

            elif item_type == 'FpPoly':
                if hasattr(item, 'coordinates') and item.coordinates:
                    points = []
                    for pt in item.coordinates:
                        rx, ry = rotate_point(pt.X, pt.Y, -fp_angle)
                        points.append((fp_x + rx, fp_y + ry))
                    if points:
                        self._graphics[layer].append(GraphicPoly(
                            points=points,
                            width=width,
                            layer=layer,
                            fill=fill
                        ))

    def _parse_board_graphics(self) -> None:
        """Extract board-level graphic items."""
        for item in self.board.graphicItems:
            layer = getattr(item, 'layer', None)
            if not layer or layer not in self._graphics:
                continue

            width = 0.1
            if hasattr(item, 'stroke') and item.stroke:
                width = item.stroke.width or 0.1

            item_type = type(item).__name__

            if item_type == 'GrLine':
                self._graphics[layer].append(GraphicLine(
                    start_x=item.start.X,
                    start_y=item.start.Y,
                    end_x=item.end.X,
                    end_y=item.end.Y,
                    width=width,
                    layer=layer
                ))
            elif item_type == 'GrArc':
                self._graphics[layer].append(GraphicArc(
                    start_x=item.start.X,
                    start_y=item.start.Y,
                    mid_x=item.mid.X if item.mid else item.start.X,
                    mid_y=item.mid.Y if item.mid else item.start.Y,
                    end_x=item.end.X,
                    end_y=item.end.Y,
                    width=width,
                    layer=layer
                ))

    def _parse_traces_and_vias(self) -> None:
        """Extract trace segments and vias from the board."""
        for item in self.board.traceItems:
            item_type = type(item).__name__

            if item_type == 'Segment':
                layer = item.layer
                if layer in self._traces:
                    net_id = item.net if item.net else 0
                    self._traces[layer].append(TraceInfo(
                        start_x=item.start.X,
                        start_y=item.start.Y,
                        end_x=item.end.X,
                        end_y=item.end.Y,
                        width=item.width,
                        layer=layer,
                        net_id=net_id,
                        net_name=self._net_names.get(net_id, "")
                    ))

            elif item_type == 'Via':
                net_id = item.net if item.net else 0
                self._vias.append(ViaInfo(
                    x=item.position.X,
                    y=item.position.Y,
                    size=item.size,
                    drill=item.drill,
                    layers=list(item.layers) if item.layers else [],
                    net_id=net_id,
                    net_name=self._net_names.get(net_id, "")
                ))

    def _calculate_bounds(self) -> None:
        """Calculate board bounding box from pads and edge cuts."""
        all_x: list[float] = []
        all_y: list[float] = []

        # Include pad positions
        for pad in self._pads:
            all_x.extend([pad.x - pad.width/2, pad.x + pad.width/2])
            all_y.extend([pad.y - pad.height/2, pad.y + pad.height/2])

        # Include edge cuts (primary bounds source)
        for item in self._graphics.get("Edge.Cuts", []):
            if isinstance(item, GraphicLine):
                all_x.extend([item.start_x, item.end_x])
                all_y.extend([item.start_y, item.end_y])
            elif isinstance(item, GraphicArc):
                all_x.extend([item.start_x, item.mid_x, item.end_x])
                all_y.extend([item.start_y, item.mid_y, item.end_y])
            elif isinstance(item, GraphicPoly):
                for px, py in item.points:
                    all_x.append(px)
                    all_y.append(py)
            elif isinstance(item, GraphicCircle):
                all_x.extend([item.center_x - item.radius, item.center_x + item.radius])
                all_y.extend([item.center_y - item.radius, item.center_y + item.radius])

        if all_x and all_y:
            self._min_x = min(all_x)
            self._max_x = max(all_x)
            self._min_y = min(all_y)
            self._max_y = max(all_y)
        else:
            self._min_x = self._max_x = self._min_y = self._max_y = 0

    @property
    def footprints(self) -> list[FootprintInfo]:
        """Get all parsed footprints."""
        return self._footprints

    @property
    def pads(self) -> list[PadInfo]:
        """Get all pads."""
        return self._pads

    @property
    def edge_cuts(self) -> list[GraphicItem]:
        """Get board outline elements."""
        return self._graphics.get("Edge.Cuts", [])

    @property
    def graphics(self) -> dict[str, list[GraphicItem]]:
        """Get all graphics organized by layer."""
        return self._graphics

    def get_graphics_by_layer(self, layer: str) -> list[GraphicItem]:
        """Get graphics for a specific layer."""
        return self._graphics.get(layer, [])

    @property
    def nets(self) -> dict[int, str]:
        """Get net ID to name mapping."""
        return self._net_names

    def get_pads_by_net(self, net_id: int) -> list[PadInfo]:
        """Get all pads belonging to a net."""
        return self._net_to_pads.get(net_id, [])

    def get_pads_by_layer(self, layer: str) -> list[PadInfo]:
        """Get all pads on a specific layer."""
        return [p for p in self._pads if layer in p.layers]

    @property
    def traces(self) -> dict[str, list[TraceInfo]]:
        """Get all traces organized by layer."""
        return self._traces

    def get_traces_by_layer(self, layer: str) -> list[TraceInfo]:
        """Get traces for a specific layer."""
        return self._traces.get(layer, [])

    @property
    def vias(self) -> list[ViaInfo]:
        """Get all vias."""
        return self._vias

    def get_board_info(self) -> BoardInfo:
        """Get overall board information."""
        total_traces = sum(len(traces) for traces in self._traces.values())
        return BoardInfo(
            min_x=self._min_x,
            min_y=self._min_y,
            max_x=self._max_x,
            max_y=self._max_y,
            layers=self.ALL_LAYERS,
            footprint_count=len(self._footprints),
            pad_count=len(self._pads),
            net_count=len(self._net_names),
            trace_count=total_traces,
            via_count=len(self._vias)
        )
