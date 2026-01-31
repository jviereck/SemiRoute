"""SVG styling constants for PCB layers."""

# Layer colors (KiCad default style)
LAYER_COLORS = {
    # Copper layers
    "F.Cu": "#C83232",      # Red - front copper
    "B.Cu": "#3232C8",      # Blue - back copper
    "In1.Cu": "#C8C832",    # Yellow - inner layer 1
    "In2.Cu": "#32C8C8",    # Cyan - inner layer 2

    # Board outline
    "Edge.Cuts": "#C8C832", # Yellow - board outline

    # Silkscreen
    "F.SilkS": "#F0F0F0",   # White - front silkscreen
    "B.SilkS": "#F0F0F0",   # White - back silkscreen

    # Fabrication
    "F.Fab": "#AFAFAF",     # Gray - front fabrication
    "B.Fab": "#AFAFAF",     # Gray - back fabrication

    # Courtyard
    "F.CrtYd": "#FF26E2",   # Magenta - front courtyard
    "B.CrtYd": "#FF26E2",   # Magenta - back courtyard
}

# Background color for the board
BACKGROUND_COLOR = "#1a1a1a"

# Highlight color for selected nets
HIGHLIGHT_COLOR = "#00FF00"

# Layer render order (back to front)
LAYER_ORDER = [
    "B.CrtYd", "B.Fab", "B.SilkS",
    "Edge.Cuts",
    "B.Cu", "In2.Cu", "In1.Cu", "F.Cu",
    "F.SilkS", "F.Fab", "F.CrtYd",
]

# Default opacities
PAD_OPACITY = 0.9
GRAPHICS_OPACITY = 0.8

# Stroke widths
EDGE_CUTS_STROKE_WIDTH = 0.15
DEFAULT_STROKE_WIDTH = 0.12
