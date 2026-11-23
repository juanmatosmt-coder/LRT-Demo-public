"""The tool's version, shown in the self-check, start.bat and the chat panel.

VERSION holds the release number (raise it when you hand out a new build). The Git commit, when the folder is a Git
clone, tells two copies with the same number apart. Read from files only: no Git command and no network.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def number():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def commit():
    """Short commit id from .git, or '' when this is not a Git clone (for example a zip copy)."""
    git = ROOT / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7]
        ref = head[5:]
        f = git / ref
        if f.exists():
            return f.read_text(encoding="utf-8").strip()[:7]
        packed = git / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line[:7]
    except OSError:
        pass
    return ""


def text():
    c = commit()
    return f"v{number()}" + (f" (commit {c})" if c else "")


if __name__ == "__main__":
    print(text())
