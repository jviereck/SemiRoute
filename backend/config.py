"""Configuration constants for the backend."""
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Default PCB file
DEFAULT_PCB_FILE = PROJECT_ROOT / "BLDriver.kicad_pcb"

# Frontend static files directory
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Server settings
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
