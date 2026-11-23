#!/usr/bin/env python3
"""Writes colab/LRT_Colab.ipynb, the Google Colab version of the tool (SYNTHETIC data only).

    python tools/make_colab_notebook.py

The notebook's code cells are plain Python (no ! or % commands), so tools/test_colab_notebook.py can run them
outside Colab too.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "colab" / "LRT_Colab.ipynb"
REPO = "juanmatosmt-coder/LRT-Demo-public"

CELLS = []


def md(text):
    CELLS.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)})


def code(text):
    CELLS.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": text.strip("\n").splitlines(keepends=True)})


md(f"""
# [SYNTHETIC] Lab Request Assistant on Google Colab

**SYNTHETIC DATA ONLY.** Everything in this notebook (procedures, parts, past requests, equipment) is invented for the
CMU / Emeritus capstone. No real names, customers, programs, part numbers, documents or results.

**Colab is Google's cloud, not your computer.** The Windows version (`install.bat`, `start.bat`) keeps everything on your
PC. This notebook runs on a Google machine instead, so:

* never upload real lab requests, company files or anything from `data/private`;
* never type real customer, program or part information into the form or the chat.

The notebook stops if it finds anything in `data/private`.

**Run the cells in order** (Runtime > Run all works too):

| Cell | What it does | Time |
|---|---|---|
| 1 | Gets the code, checks that no private data is present, shows the version | < 1 min |
| 2 | Non-AI self-check (the same check as `install.bat`) | ~10 s |
| 3 | Asks the assistant from the notebook (no AI unless cell 4 has run) | seconds |
| 4 | Optional: the local AI model on Colab's GPU (Runtime > Change runtime type > **T4 GPU**) | 10-25 min the first time |
| 5 | Opens the form page with the chat in a new browser tab | < 1 min |
| 6 | Security tests | ~1 min |
| 7 | Stops the servers | |

**Getting the code.** Cell 1 clones the public repository `{REPO}`. Only if that fails (no access to GitHub, or a
private fork), it takes a SYNTHETIC zip instead. Make the zip on your PC, in the project folder:

```
git archive -o LRT-Demo-synthetic.zip HEAD
```

`git archive` packs only committed files, so `data/private` is never included. Then give it to cell 1 in one of three ways
(it tries them in this order):

* **A. Google Drive (recommended, no re-upload each time):** put the zip in *My Drive* as `LRT-Demo-synthetic.zip`.
  Cell 1 asks to connect your Drive and reads it from `/content/drive/MyDrive/LRT-Demo-synthetic.zip`.
* **B. A share link:** in Drive, *Share > General access > Anyone with the link*, copy the link and paste it into
  `ZIP_URL` in cell 1 (a Google Drive link or any direct https link to the zip). Anyone with that link can download
  the zip, which is why it must contain SYNTHETIC data only.
* **C. Upload:** if neither is set, cell 1 shows an upload button.

With the public repository none of this is needed.
""")

code(r'''
# 1. Get the code (SYNTHETIC data only), check that no private data is present, show the version
import glob, json, os, shutil, subprocess, sys, time, urllib.request, zipfile

REPO_URL = "https://github.com/''' + REPO + r'''.git"     # the public repository
DRIVE_ZIP = "/content/drive/MyDrive/LRT-Demo-synthetic.zip"   # A: the zip in your Google Drive ("" to skip)
ZIP_URL = ""                                                   # B: a share link to the zip (Google Drive or any https link)
WORK = os.environ.get("LRT_DIR", "/content/LRT-Demo")
IN_COLAB = "google.colab" in sys.modules
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # local addresses never go through a proxy


def unzip_into_work(path, keep=False):
    tmp = WORK + "_unzip"
    shutil.rmtree(tmp, ignore_errors=True)
    zipfile.ZipFile(path).extractall(tmp)
    tops = [tmp] + sorted(glob.glob(tmp + "/*/"))
    top = next(t for t in tops if os.path.exists(os.path.join(t, "gui", "serve.py")))
    shutil.move(top, WORK)
    shutil.rmtree(tmp, ignore_errors=True)
    if not keep:
        os.remove(path)


def download(url, dest="/content/LRT-Demo-synthetic.zip"):
    """A Google Drive share link (.../file/d/<id>/...) or any direct https link to the zip."""
    import re
    m = re.search(r"/file/d/([\w-]+)|[?&]id=([\w-]+)", url)
    if "drive.google.com" in url and m:
        url = "https://drive.google.com/uc?export=download&id=" + (m.group(1) or m.group(2))
    urllib.request.urlretrieve(url, dest)
    if not zipfile.is_zipfile(dest):
        raise RuntimeError("The link did not return a zip. For Google Drive, set General access to 'Anyone with the link'.")
    return dest


if not os.path.exists(os.path.join(WORK, "gui", "serve.py")):
    r = subprocess.run(["git", "clone", "-q", "--depth", "1", REPO_URL, WORK], capture_output=True, text=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        if not IN_COLAB:
            raise RuntimeError("Could not clone " + REPO_URL + ". Set LRT_DIR to a copy of the project.")
        got = False
        if DRIVE_ZIP:                                     # A. Google Drive
            try:
                from google.colab import drive
                drive.mount("/content/drive")
                if os.path.exists(DRIVE_ZIP):
                    unzip_into_work(DRIVE_ZIP, keep=True)
                    got = True
                    print("Code from Google Drive:", DRIVE_ZIP)
                else:
                    print("Not in Drive:", DRIVE_ZIP)
            except Exception as e:
                print("Google Drive not used:", e)
        if not got and ZIP_URL:                           # B. share link
            unzip_into_work(download(ZIP_URL))
            got = True
            print("Code from the link.")
        if not got:                                       # C. upload
            print("Upload LRT-Demo-synthetic.zip, made on your PC with:  git archive -o LRT-Demo-synthetic.zip HEAD")
            from google.colab import files
            uploaded = files.upload()
            unzip_into_work(next(iter(uploaded)))
os.chdir(WORK)
sys.path.insert(0, WORK)

private = [p for p in glob.glob("data/private/**/*", recursive=True)
           if os.path.isfile(p) and os.path.basename(p) != "README.md"]
if private:
    raise RuntimeError(f"STOP: data/private holds {len(private)} file(s). Colab is Google's cloud: SYNTHETIC data only. "
                       "Use Runtime > Disconnect and delete runtime, then upload a zip made with git archive.")

import lrt_version
print("Lab Request Assistant", lrt_version.text())
print("Folder:", WORK)
print("data/private: empty (SYNTHETIC data only)")
''')

md("""
## 2. Non-AI self-check

The same check `install.bat` runs: version, data files, quality-check known answers, guardrails, one chat turn by
rules, the local-only rules and a web-server smoke test. The AI model is not used here.
""")

code(r'''
# 2. Non-AI self-check
r = subprocess.run([sys.executable, "tools/selfcheck.py"], capture_output=True, text=True)
print(r.stdout[-6000:] or r.stderr[-3000:])
SELF_CHECK_OK = r.returncode == 0
''')

md("""
## 3. Ask the assistant from the notebook

Change the message and run the cell again. Without the AI model (cell 4) the draft is built by fixed rules, and the
reply says so. It proposes field values; nothing is ever submitted.
""")

code(r'''
# 3. Ask the assistant (uses the AI model if cell 4 started it, otherwise fixed rules)
def model_up():
    try:
        with LOCAL.open("http://127.0.0.1:8000/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ask(message, form="lab_test_request"):
    env = dict(os.environ)
    if model_up():
        env.pop("LRT_STUB_LLM", None)
    else:
        env["LRT_STUB_LLM"] = "1"
    prog = ("import json, sys; from assistant.chat import assist; "
            "print('@@' + json.dumps(assist(sys.argv[1], form_key=sys.argv[2])))")
    p = subprocess.run([sys.executable, "-c", prog, message, form], env=env, capture_output=True, text=True, timeout=900)
    out = [l for l in p.stdout.splitlines() if l.startswith("@@")]
    if not out:
        print(p.stderr[-2000:])
        return None
    r = json.loads(out[-1][2:])
    print(f"Mode: {r['mode']}    State: {r['state']}\n")
    print(r["reply"], "\n")
    if r["changes"]:
        print("Proposed for the draft:")
        for k in r["changes"]:
            key = k.split(".")[0]
            print(f"  {k}: {r['proposed'].get(key)}")
    if r["citations"]:
        print("\nProcedures cited:")
        for c in r["citations"]:
            print(f"  {c['doc_id']} Rev {c['revision']}  {c['section'].split(' - ')[-1]}")
    if r["flags"]:
        print("\nStill to fix:")
        for f in r["flags"][:6]:
            print(f"  [{f['severity']}] {f['message']}")
    return r


result = ask("Measure warpage on 10 SYN-10001 housings through reflow, peak 260 C, to confirm the new mold before release.")
''')

md("""
## 4. Optional: the AI model on Colab's GPU

Needs a GPU runtime: **Runtime > Change runtime type > T4 GPU** (free tier), then run cells 1-4 again. The first run
downloads Qwen3.5-9B and the embedding model from Hugging Face (about 20 GB, 10-25 minutes) into this runtime; they
are deleted when the runtime ends. The model runs inside the Colab machine at 127.0.0.1:8000.

Set `USE_AI = False` to skip it: the tool works without AI (drafts by fixed rules).
""")

code(r'''
# 4. Optional: start the AI model on the GPU
USE_AI = True
MODEL_LOG = os.path.join(WORK, "traces", "qwen_server.log")


def gpu_name():
    if not shutil.which("nvidia-smi"):
        return ""
    r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
    return r.stdout.strip()


if not USE_AI:
    print("Skipped: the assistant drafts by fixed rules (no AI).")
elif model_up():
    print("The AI model is already running.")
elif not gpu_name():
    print("No GPU in this runtime. Use Runtime > Change runtime type > T4 GPU, then run cells 1-4 again.\n"
          "Everything else works without it (drafts by fixed rules).")
else:
    print("GPU:", gpu_name())
    print("Installing the model packages ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "transformers", "accelerate", "bitsandbytes",
                    "sentence-transformers", "fastapi", "uvicorn"], check=True)
    os.makedirs(os.path.dirname(MODEL_LOG), exist_ok=True)
    env = {**os.environ, "LRT_ALLOW_DOWNLOAD": "1"}            # the one place the model files may be downloaded
    env.pop("LRT_STUB_LLM", None)
    MODEL_PROC = subprocess.Popen([sys.executable, "spikes/qwen_server.py"], env=env,
                                  stdout=open(MODEL_LOG, "w"), stderr=subprocess.STDOUT)
    print("Downloading and loading the model (10-25 minutes the first time) ...")
    t0 = time.time()
    while not model_up():
        if MODEL_PROC.poll() is not None:
            print("The model server stopped. Last lines of its log:\n" + open(MODEL_LOG).read()[-3000:])
            break
        if time.time() - t0 > 45 * 60:
            print("Still not ready after 45 minutes; see", MODEL_LOG)
            break
        time.sleep(30)
        last = [l for l in open(MODEL_LOG).read().splitlines() if l.strip()][-1:]
        print(f"  {int(time.time() - t0)} s  {last[0][:110] if last else ''}")
    if model_up():
        print(f"AI model ready after {int(time.time() - t0)} s. Run cell 3 again: Mode should name the model, e.g. AI (Qwen3.5-9B · 4-bit · Tesla T4 · this computer).")
''')

md("""
## 5. Open the form page

Opens the form and the chat in a new browser tab through Colab's private proxy (only you can open it). If the AI model
from cell 4 is running, the chat badge says **AI on**; otherwise **Demo: no AI**. Run this cell again after cell 4
to switch the page to the AI. Drafts stay in your browser; sign-in is off in Colab.
""")

code(r'''
# 5. Start the web server and open the form page
PORT = 8010
PAGE = f"http://127.0.0.1:{PORT}/gui/request_form.html"
if globals().get("GUI_PROC") and GUI_PROC.poll() is None:
    GUI_PROC.terminate(); GUI_PROC.wait(10)
env = dict(os.environ)
if model_up():
    env.pop("LRT_STUB_LLM", None)
else:
    env["LRT_STUB_LLM"] = "1"
os.makedirs("traces", exist_ok=True)
GUI_PROC = subprocess.Popen([sys.executable, "gui/serve.py", "--colab", "--port", str(PORT)], env=env,
                            stdout=open("traces/gui.log", "w"), stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        with LOCAL.open(PAGE, timeout=2) as r:
            if r.status == 200:
                break
    except Exception:
        time.sleep(0.5)
else:
    raise RuntimeError("The web server did not start:\n" + open("traces/gui.log").read()[-2000:])
print("Web server running", "with the AI model." if "LRT_STUB_LLM" not in env else "without AI (demo: fixed rules).")
if IN_COLAB:
    from google.colab import output
    output.serve_kernel_port_as_window(PORT, path="/gui/request_form.html", anchor_text="Open the Lab Request Assistant")
else:
    print("Open:", PAGE)
''')

md("""
## 6. Security tests

The repository's security tests: guardrails, blocked files, no outbound traffic, the assistant never submits or approves.
""")

code(r'''
# 6. Security tests
r = subprocess.run([sys.executable, "tests/test_security.py"], capture_output=True, text=True, timeout=900)
print("\n".join(r.stdout.splitlines()[-25:]) or r.stderr[-3000:])
''')

md("""
## 7. Stop

Stops the web server and the AI model. To remove everything (code, model files, logs) use
**Runtime > Disconnect and delete runtime**.
""")

code(r'''
# 7. Stop the servers
for name in ("GUI_PROC", "MODEL_PROC"):
    p = globals().get(name)
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            p.kill()
        print("Stopped", name)
''')


def main():
    nb = {"cells": CELLS, "metadata": {
        "accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4", "name": "LRT_Colab.ipynb"},
        "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 0}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({sum(c['cell_type'] == 'code' for c in CELLS)} code cells)")


if __name__ == "__main__":
    main()
