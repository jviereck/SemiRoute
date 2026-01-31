"""SVG document generator for PCB visualization."""
from xml.etree.ElementTree import Element, SubElement, tostring

from backend.pcb.parser import PCBParser

from .elements import create_drill_hole, create_graphic_element, create_pad_element
from .styles import BACKGROUND_COLOR, LAYER_ORDER


# Copper layers that have pads
COPPER_LAYERS = {"F.Cu", "B.Cu", "In1.Cu", "In2.Cu"}

# Default clearance value in mm
DEFAULT_CLEARANCE = 0.2


class SVGGenerator:
    """Generate SVG representation of a PCB."""

    def __init__(self, parser: PCBParser):
        """Initialize with a parsed PCB."""
        self.parser = parser
        self.board_info = parser.get_board_info()

    def generate(self, layers: list[str] | None = None, margin: float = 2.0) -> str:
        """
        Generate SVG document.

        Args:
            layers: List of layers to include, or None for all
            margin: Margin around the board (mm)

        Returns:
            SVG document as string
        """
        if layers is None:
            layers = LAYER_ORDER

        # Calculate viewBox with margin
        min_x = self.board_info.min_x - margin
        min_y = self.board_info.min_y - margin
        width = self.board_info.width + 2 * margin
        height = self.board_info.height + 2 * margin

        # Create SVG root element
        svg = Element("svg", {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"{min_x:.4f} {min_y:.4f} {width:.4f} {height:.4f}",
            "width": "100%",
            "height": "100%",
            "preserveAspectRatio": "xMidYMid meet",
        })

        # Add CSS styles
        style = SubElement(svg, "style")
        style.text = self._generate_css()

        # Background
        SubElement(svg, "rect", {
            "class": "background",
            "x": f"{min_x:.4f}",
            "y": f"{min_y:.4f}",
            "width": f"{width:.4f}",
            "height": f"{height:.4f}",
            "fill": BACKGROUND_COLOR,
        })

        # Add clearance layer (rendered first, behind everything)
        clearance_group = SubElement(svg, "g", {
            "id": "layer-Clearance",
            "class": "layer clearance-layer hidden",
            "data-layer": "Clearance",
        })
        self._add_clearances(clearance_group)

        # Create layer groups in render order
        for layer in LAYER_ORDER:
            if layer not in layers:
                continue

            group = SubElement(svg, "g", {
                "id": f"layer-{layer.replace('.', '-')}",
                "class": "layer",
                "data-layer": layer,
            })

            # Add graphics for this layer
            self._add_layer_graphics(group, layer)

            # Add traces and pads for copper layers
            if layer in COPPER_LAYERS:
                self._add_layer_traces(group, layer)
                self._add_layer_pads(group, layer)

        # Add vias on top of traces
        via_group = SubElement(svg, "g", {
            "id": "vias",
            "class": "via-layer",
        })
        self._add_vias(via_group)

        # Add drill holes on top
        drill_group = SubElement(svg, "g", {
            "id": "drill-holes",
            "class": "drill-layer",
        })
        self._add_drill_holes(drill_group)
        self._add_via_holes(drill_group)

        # Convert to string
        return tostring(svg, encoding="unicode")

    def _generate_css(self) -> str:
        """Generate CSS styles for the SVG."""
        return """
            .pad { cursor: pointer; pointer-events: all; }
            .pad:hover { filter: brightness(1.3); }
            .pad.highlighted {
                fill: #00FF00 !important;
                fill-opacity: 0.9 !important;
            }
            .trace { pointer-events: none; }
            .trace.highlighted {
                stroke: #00FF00 !important;
                stroke-opacity: 1 !important;
            }
            .via { cursor: pointer; pointer-events: all; }
            .via:hover { filter: brightness(1.3); }
            .via.highlighted {
                fill: #00FF00 !important;
                fill-opacity: 0.9 !important;
            }
            .layer { pointer-events: none; }
            .layer.hidden { display: none; }
            .drill-layer { pointer-events: none; }
            .via-layer { pointer-events: none; }
            .clearance-layer { pointer-events: none; }
            .clearance { fill: none; stroke: #FF6600; stroke-opacity: 0.5; }
            .clearance-fill { fill: #FF6600; fill-opacity: 0.15; stroke: none; }
        """

    def _add_layer_graphics(self, group: Element, layer: str) -> None:
        """Add graphic elements for a specific layer."""
        for item in self.parser.get_graphics_by_layer(layer):
            elem = create_graphic_element(item)
            group.append(elem)

    def _add_layer_traces(self, group: Element, layer: str) -> None:
        """Add traces for a specific layer to a group."""
        from .styles import LAYER_COLORS
        color = LAYER_COLORS.get(layer, "#888888")

        for trace in self.parser.get_traces_by_layer(layer):
            elem = Element("line", {
                "x1": f"{trace.start_x:.4f}",
                "y1": f"{trace.start_y:.4f}",
                "x2": f"{trace.end_x:.4f}",
                "y2": f"{trace.end_y:.4f}",
                "stroke": color,
                "stroke-width": f"{trace.width:.4f}",
                "stroke-linecap": "round",
                "stroke-opacity": "0.9",
                "class": "trace",
                "data-net": str(trace.net_id),
                "data-net-name": trace.net_name,
            })
            group.append(elem)

    def _add_layer_pads(self, group: Element, layer: str) -> None:
        """Add pads for a specific layer to a group."""
        for pad in self.parser.pads:
            elem = create_pad_element(pad, layer)
            if elem is not None:
                group.append(elem)

    def _add_vias(self, group: Element) -> None:
        """Add vias to a group."""
        for via in self.parser.vias:
            # Via is rendered as a circle on each layer it connects
            # Use a neutral color (gold/yellow) for vias
            elem = Element("circle", {
                "cx": f"{via.x:.4f}",
                "cy": f"{via.y:.4f}",
                "r": f"{via.size / 2:.4f}",
                "fill": "#C8A832",  # Gold color for vias
                "fill-opacity": "0.9",
                "class": "via",
                "data-net": str(via.net_id),
                "data-net-name": via.net_name,
            })
            group.append(elem)

    def _add_drill_holes(self, group: Element) -> None:
        """Add drill holes to a group."""
        for pad in self.parser.pads:
            elem = create_drill_hole(pad)
            if elem is not None:
                group.append(elem)

    def _add_via_holes(self, group: Element) -> None:
        """Add via drill holes to a group."""
        for via in self.parser.vias:
            elem = Element("circle", {
                "cx": f"{via.x:.4f}",
                "cy": f"{via.y:.4f}",
                "r": f"{via.drill / 2:.4f}",
                "fill": "#1a1a1a",  # Background color
                "class": "via-hole",
            })
            group.append(elem)

    def _add_clearances(self, group: Element, clearance: float = DEFAULT_CLEARANCE) -> None:
        """Add clearance zones around pads, vias, and traces."""
        # Clearances for pads (render for each copper layer)
        for pad in self.parser.pads:
            for layer in pad.layers:
                if layer in COPPER_LAYERS:
                    self._add_pad_clearance(group, pad, clearance)
                    break  # Only add once per pad

        # Clearances for vias
        for via in self.parser.vias:
            elem = Element("circle", {
                "cx": f"{via.x:.4f}",
                "cy": f"{via.y:.4f}",
                "r": f"{via.size / 2 + clearance:.4f}",
                "class": "clearance-fill",
            })
            group.append(elem)

        # Clearances for traces
        for layer in COPPER_LAYERS:
            for trace in self.parser.get_traces_by_layer(layer):
                elem = Element("line", {
                    "x1": f"{trace.start_x:.4f}",
                    "y1": f"{trace.start_y:.4f}",
                    "x2": f"{trace.end_x:.4f}",
                    "y2": f"{trace.end_y:.4f}",
                    "stroke": "#FF6600",
                    "stroke-width": f"{trace.width + 2 * clearance:.4f}",
                    "stroke-linecap": "round",
                    "stroke-opacity": "0.15",
                    "class": "clearance",
                })
                group.append(elem)

    def _add_pad_clearance(self, group: Element, pad, clearance: float) -> None:
        """Add clearance zone for a single pad."""
        # Expand pad dimensions by clearance
        expanded_width = pad.width + 2 * clearance
        expanded_height = pad.height + 2 * clearance

        if pad.shape == "circle":
            radius = min(pad.width, pad.height) / 2 + clearance
            elem = Element("circle", {
                "cx": f"{pad.x:.4f}",
                "cy": f"{pad.y:.4f}",
                "r": f"{radius:.4f}",
                "class": "clearance-fill",
            })
        elif pad.shape == "oval":
            elem = Element("ellipse", {
                "cx": f"{pad.x:.4f}",
                "cy": f"{pad.y:.4f}",
                "rx": f"{expanded_width / 2:.4f}",
                "ry": f"{expanded_height / 2:.4f}",
                "class": "clearance-fill",
            })
        else:  # rect, roundrect
            corner_radius = 0
            if pad.shape == "roundrect":
                corner_radius = pad.roundrect_ratio * min(expanded_width, expanded_height) / 2

            if pad.angle != 0:
                # For rotated pads, use a polygon approximation
                import math
                w2, h2 = expanded_width / 2, expanded_height / 2
                corners = [
                    (pad.x - w2, pad.y - h2),
                    (pad.x + w2, pad.y - h2),
                    (pad.x + w2, pad.y + h2),
                    (pad.x - w2, pad.y + h2),
                ]
                angle_rad = math.radians(pad.angle)
                cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
                rotated = []
                for px, py in corners:
                    dx, dy = px - pad.x, py - pad.y
                    rx = pad.x + dx * cos_a - dy * sin_a
                    ry = pad.y + dx * sin_a + dy * cos_a
                    rotated.append(f"{rx:.4f},{ry:.4f}")
                elem = Element("polygon", {
                    "points": " ".join(rotated),
                    "class": "clearance-fill",
                })
            else:
                elem = Element("rect", {
                    "x": f"{pad.x - expanded_width / 2:.4f}",
                    "y": f"{pad.y - expanded_height / 2:.4f}",
                    "width": f"{expanded_width:.4f}",
                    "height": f"{expanded_height:.4f}",
                    "rx": f"{corner_radius:.4f}",
                    "ry": f"{corner_radius:.4f}",
                    "class": "clearance-fill",
                })

        group.append(elem)
