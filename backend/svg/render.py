"""SVG to PNG rendering utilities."""
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image


def render_svg_to_png(
    svg_content: str,
    output_path: str | Path | None = None,
    scale: float = 10.0,
) -> Image.Image:
    """
    Render SVG content to a PNG image.

    Args:
        svg_content: SVG document as a string
        output_path: Optional path to save the PNG file
        scale: Scale factor for rendering (default 10x for detail)

    Returns:
        PIL Image object
    """
    # Convert SVG to PNG bytes
    png_bytes = cairosvg.svg2png(
        bytestring=svg_content.encode('utf-8'),
        scale=scale,
    )

    # Load as PIL Image
    image = Image.open(BytesIO(png_bytes))

    # Save if path provided
    if output_path:
        image.save(str(output_path))

    return image


def render_pcb_to_png(
    pcb_path: str | Path,
    output_path: str | Path | None = None,
    layers: list[str] | None = None,
    scale: float = 10.0,
) -> Image.Image:
    """
    Render a KiCad PCB file to PNG.

    Args:
        pcb_path: Path to the .kicad_pcb file
        output_path: Optional path to save the PNG file
        layers: List of layers to include, or None for all
        scale: Scale factor for rendering

    Returns:
        PIL Image object
    """
    from backend.pcb import PCBParser
    from backend.svg import SVGGenerator

    parser = PCBParser(pcb_path)
    generator = SVGGenerator(parser)
    svg_content = generator.generate(layers=layers)

    return render_svg_to_png(svg_content, output_path, scale)
