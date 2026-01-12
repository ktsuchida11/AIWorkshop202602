import sys
from pathlib import Path
import os

# Ensure project root (one level up from tests/) is on sys.path so tests can import server
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Prevent the MCP server from starting during test collection/imports
os.environ.setdefault("MCP_TESTING", "1")
