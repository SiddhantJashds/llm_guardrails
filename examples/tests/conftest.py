import sys
from pathlib import Path

# examples/ isn't a package (the scripts run as `uv run examples/x.py`), so make
# its sibling modules importable the same way that run puts them on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
