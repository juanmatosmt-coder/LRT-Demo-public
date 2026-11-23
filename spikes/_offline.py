"""Import first in every spike: applies the repo's no-outbound-traffic policy (see lrt_offline.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lrt_offline  # noqa: E402,F401
