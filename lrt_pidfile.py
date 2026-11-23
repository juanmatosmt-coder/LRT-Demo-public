"""PID files for the two local servers, so stop.bat can stop them however their windows were opened
(a console window, or a tab in Windows Terminal, where the window-title method cannot find them)."""
import atexit
import os
from pathlib import Path

DIR = Path(__file__).resolve().parent / "traces"


def write(name, port):
    DIR.mkdir(parents=True, exist_ok=True)
    f = DIR / f"{name}.pid"
    f.write_text(f"{os.getpid()} {port}\n")

    def _remove():
        try:
            if f.read_text().split()[0] == str(os.getpid()):
                f.unlink()
        except (OSError, IndexError):
            pass
    atexit.register(_remove)
    return f
