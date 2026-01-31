"""Configuration constants for the backend."""
import subprocess
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Default PCB file
DEFAULT_PCB_FILE = PROJECT_ROOT / "BLDriver.kicad_pcb"

# Frontend static files directory
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Server settings
DEFAULT_HOST = "0.0.0.0"
BASE_PORT = 8000


def get_port_from_git_branch() -> int:
    """
    Determine server port based on current git branch.

    - main: 8000
    - *-a: 8001
    - *-b: 8002
    - etc.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        branch = result.stdout.strip()
    except Exception:
        return BASE_PORT

    if branch == "main":
        return BASE_PORT

    # Check for branch ending in -<letter>
    if len(branch) >= 2 and branch[-2] == "-":
        suffix = branch[-1].lower()
        if suffix.isalpha():
            # 'a' -> 1, 'b' -> 2, etc.
            offset = ord(suffix) - ord('a') + 1
            return BASE_PORT + offset

    return BASE_PORT


DEFAULT_PORT = get_port_from_git_branch()
