#!/usr/bin/env python3
"""Runs the code cells of colab/LRT_Colab.ipynb outside Colab, on a copy made with git archive (as a user uploads it).

    python tests/test_colab_notebook.py

Checks: the notebook runs top to bottom, the self-check passes, the assistant answers, the web server starts in
--colab mode, the security tests pass, and the notebook refuses a copy that contains data/private files.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "colab" / "LRT_Colab.ipynb"


def cells():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def run_notebook(work):
    os.environ["LRT_DIR"] = str(work)
    ns, out = {"__name__": "__main__"}, io.StringIO()
    cwd = os.getcwd()
    try:
        with contextlib.redirect_stdout(out):
            for i, src in enumerate(cells(), 1):
                exec(compile(src, f"cell {i}", "exec"), ns)
    finally:
        os.chdir(cwd)
    return ns, out.getvalue()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lrt_colab_"))
    zpath = tmp / "LRT-Demo-synthetic.zip"
    subprocess.run(["git", "archive", "--prefix=LRT-Demo-main/", "-o", str(zpath), "HEAD"], cwd=ROOT, check=True)
    results = []
    try:
        # the upload path: unzip a git archive (with a top folder, like GitHub's Download ZIP)
        src = cells()[0]
        helper = src[src.index("def unzip_into_work"):src.index("if not os.path.exists")]
        ns = {"WORK": str(tmp / "LRT-Demo"), "os": os, "glob": __import__("glob"), "shutil": shutil,
              "zipfile": __import__("zipfile")}
        exec(helper, ns)
        ns["unzip_into_work"](str(zpath))
        work = tmp / "LRT-Demo"
        results.append(("upload zip unpacks to the project folder", (work / "gui" / "serve.py").exists()))

        ns, out = run_notebook(work)
        results += [
            ("cell 1: version shown, data/private empty", "Lab Request Assistant v" in out and "data/private: empty" in out),
            ("cell 2: non-AI self-check passed", ns.get("SELF_CHECK_OK") is True),
            ("cell 3: assistant answered (no AI)", bool(ns.get("result")) and ns["result"]["citations"] != []),
            ("cell 4: no GPU here, skipped cleanly", "No GPU" in out or "AI model ready" in out),
            ("cell 5: web server started in Colab mode", "Web server running" in out),
            ("cell 6: security tests passed", "passed" in out and "FAIL " not in out.split("# 6")[-1]),
            ("cell 7: servers stopped", "Stopped GUI_PROC" in out),
        ]
        # a copy with private data must be refused
        (work / "data" / "private" / "lab_requests").mkdir(parents=True, exist_ok=True)
        (work / "data" / "private" / "lab_requests" / "LR-x.json").write_text("{}")
        try:
            run_notebook(work)
            refused = False
        except RuntimeError as e:
            refused = "STOP: data/private" in str(e)
        results.append(("refuses a copy with data/private files", refused))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    bad = sum(not ok for _, ok in results)
    print(f"\n{len(results) - bad}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
