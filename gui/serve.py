#!/usr/bin/env python3
r"""
Local page server and draft store for the request forms. See SECURITY.md for the threat model.

  python gui\serve.py                       this computer only: http://127.0.0.1:8010/gui/request_form.html
  python gui\serve.py --allow-lan           also your phone on the same network (inbound only; sign-up off)
  python gui\serve.py --allow-lan --tls-cert cert.pem --tls-key key.pem     the same over HTTPS
  python gui\serve.py --make-admin NAME     let an account edit the lab data (equipment, parts)

What it serves
  - Only what the pages need: gui/, data/templates/, data/synthetic/, and a short list of files in data/private/
    (real lists, logos, parts directory, example requests). Nothing else: no .git, no traces, no source code, no
    hidden files, no directory listings. data/private/ files go only to this computer or to signed-in users.
  - Drafts of signed-in users: data/private/drafts/<user>/<id>.json, written atomically (temp file, then swap).
  - Accounts: data/private/users.json with salted PBKDF2 hashes (never passwords). Sign-in cookies are signed with
    data/private/.session_key. Signing out ends every session of that account. 5 failed sign-ins lock the account
    for 15 minutes. Only admins edit lab data; the first account created on this computer becomes admin.

Requests it refuses
  - A Host header that is not this computer or an IP address (blocks DNS-rebinding attacks from web pages).
  - Writes that are not JSON from this page (blocks cross-site request forgery).
Makes no outbound connections.
"""
import argparse
import base64
import functools
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
import posixpath
import re
import secrets
import ssl
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ASSISTANT_LOCK = threading.Lock()
from lrt_offline import LOOPBACK  # noqa: E402
import equipment_db  # noqa: E402

PRIVATE = ROOT / "data" / "private"
USERS = PRIVATE / "users.json"
DRAFTS = PRIVATE / "drafts"
KEY_FILE = PRIVATE / ".session_key"
COOKIE = "lrt_session"
SESSION_DAYS = 30
MAX_BODY = 2 * 1024 * 1024
MAX_DRAFTS_PER_USER = 500
USER_RE = re.compile(r"^[a-z0-9._-]{2,32}$")
LOCK = threading.Lock()
FEEDBACK_SENT = {}                 # client -> times of recent feedback entries (rate limit)
LOCAL_CLIENTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def is_colab_host(host):
    """Google Colab's proxy for a port in this notebook, e.g. abc123-8010-colab.googleusercontent.com."""
    name = host.split(":")[0]
    return name.endswith("-colab.googleusercontent.com") or name.endswith(".colab.dev") or name.endswith(".prod.colab.dev")


def private_data_present():
    """True if data/private holds anything besides its README (real company data must never reach a cloud notebook)."""
    d = ROOT / "data" / "private"
    return d.exists() and any(p.name != "README.md" for p in d.iterdir())

# Static files the pages may load. Anything else is "not found".
PUBLIC_PREFIXES = ("/gui/", "/data/templates/", "/data/synthetic/")
PRIVATE_FILES = ("/data/private/branding/", "/data/private/lab_request_forms_schema.json",
                 "/data/private/parts/parts.json", "/data/private/lab_requests/")
STATIC_TYPES = (".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico")
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; "
            "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")

# Editable lab data sets: data/<set>/<folder>/<file>; set is "private" (real, gitignored) or "synthetic".
DATASETS = {"equipment": ("equipment", "lab_equipment.json"), "parts": ("parts", "parts.json")}

# Sign-in throttling (in memory): failures per (client, user) and per client.
FAILS = {}
LOCKOUT_FAILS, LOCKOUT_WINDOW_S = 5, 15 * 60
REGISTRATIONS = {}


def data_file(name, which):
    folder, file = DATASETS[name]
    return ROOT / "data" / which / folder / file


def validate_dataset(name, d):
    if not isinstance(d, dict):
        return ["not a JSON object"]
    if name == "equipment":
        if not isinstance(d.get("equipment"), list) or not isinstance(d.get("test_methods"), list):
            return ["needs 'equipment' and 'test_methods' lists"]
        return equipment_db.validate(d)
    if name == "parts":
        if not isinstance(d.get("parts"), list):
            return ["needs a 'parts' list"]
        seen, errs = set(), []
        for p in d["parts"]:
            if not isinstance(p, dict):
                errs.append("each part must be an object")
                continue
            k = (str(p.get("part_number", "")).strip(), str(p.get("rev", "")).strip())
            if not k[0]:
                errs.append("a part has no part_number")
            elif k in seen:
                errs.append(f"duplicate part {k[0]} rev {k[1]}")
            seen.add(k)
        return errs
    return ["unknown data set"]


# ---------- storage ----------
def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)          # owner only (no effect on Windows ACLs, which default to the user profile)
    except OSError:
        pass


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def session_key():
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
    return KEY_FILE.read_bytes()


# ---------- accounts ----------
def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(dk).decode(), "iter": 240_000}


def check_password(rec, password):
    salt = base64.b64decode(rec["salt"])
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rec.get("iter", 240_000))
    return hmac.compare_digest(base64.b64encode(dk).decode(), rec["hash"])


def make_token(user, sv):
    exp = int(time.time()) + SESSION_DAYS * 86400
    msg = f"{user}|{exp}|{sv}"
    sig = hmac.new(session_key(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}|{sig}".encode()).decode()


def read_token(token):
    try:
        user, exp, sv, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except Exception:
        return None
    good = hmac.new(session_key(), f"{user}|{exp}|{sv}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good) or int(exp) < time.time():
        return None
    rec = read_json(USERS, {}).get(user)
    return user if rec and str(rec.get("sv", 0)) == sv else None   # sign-out bumps sv and ends every session


def locked_out(client, name):
    now = time.time()
    for key in ((client, name), (client, "*")):
        hits = [t for t in FAILS.get(key, []) if now - t < LOCKOUT_WINDOW_S]
        FAILS[key] = hits
        if len(hits) >= (LOCKOUT_FAILS if key[1] != "*" else LOCKOUT_FAILS * 4):
            return int(LOCKOUT_WINDOW_S - (now - hits[0]))
    return 0


def note_failure(client, name):
    for key in ((client, name), (client, "*")):
        FAILS.setdefault(key, []).append(time.time())


def is_ip_host(host):
    h = host.rsplit(":", 1)[0].strip("[]") if not host.startswith("[") or "]:" in host else host.strip("[]")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


# ---------- HTTP ----------
class Handler(http.server.SimpleHTTPRequestHandler):
    allow_register = True          # accounts created from other devices on the network
    register_local = True          # accounts created on this computer
    lan = False
    tls = False
    port = 8010
    extra_hosts = set()
    colab = False                  # --colab: also accept Google Colab's per-notebook proxy (synthetic data only)

    # -- trust
    def client_is_local(self):
        # In --colab mode the server still listens on 127.0.0.1 only, so every client is inside the Colab VM
        # (Colab's proxy, which only the notebook's owner can open). data/private is empty there by rule.
        return self.client_address[0] in LOCAL_CLIENTS or self.colab

    def host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0].strip("[]") if host.count(":") <= 1 or host.startswith("[") else host
        if name in ("127.0.0.1", "localhost", "::1") or host in self.extra_hosts:
            return True
        if self.colab and is_colab_host(host):
            return True
        return self.lan and is_ip_host(host)

    def trusted(self):
        """May see data/private: this computer, or a signed-in user on the network."""
        return self.client_is_local() or bool(self.user())

    def set_for(self, name, requested):
        """Which data set a client may read: private only when trusted."""
        has_private = data_file(name, "private").exists()
        which = requested or ("private" if has_private and self.trusted() else "synthetic")
        if which == "private" and not self.trusted():
            return None
        return which if which in ("private", "synthetic") else None

    # -- headers
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Content-Security-Policy", PAGE_CSP)
        if self.tls:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[gui] {self.client_address[0]} " + fmt % args + "\n")

    # -- helpers
    def user(self):
        if not hasattr(self, "_user"):
            self._user = None
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    self._user = read_token(v)
        return self._user

    def can_register(self):
        return self.register_local if self.client_is_local() else self.allow_register

    def is_admin(self):
        u = self.user()
        return bool(u and read_json(USERS, {}).get(u, {}).get("admin"))

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("too large")
        d = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(d, dict):
            raise ValueError("JSON object expected")
        return d

    def send_json(self, code, obj, cookie=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, code, text, ctype, filename=None):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    # -- feedback (assistant/feedback.py): who wrote it, and who may see and manage it
    def feedback_path(self):
        from assistant import feedback
        return ROOT / "traces" / "feedback" / "feedback.jsonl" if self.colab else feedback.PATH

    def feedback_by(self):
        return self.user() or ("this computer" if self.client_is_local() else "guest")

    def can_manage_feedback(self):
        """Admins, and whoever sits at the server computer, see all feedback and set its status."""
        return self.is_admin() or self.client_is_local()

    def not_found(self):
        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def cookie(self, token, max_age):
        return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}" + ("; Secure" if self.tls else "")

    def same_origin(self, origin):
        netloc = urlparse(origin).netloc.lower()
        if netloc == (self.headers.get("Host") or "").lower():
            return True
        return self.colab and urlparse(origin).scheme == "https" and is_colab_host(netloc)

    def write_allowed(self):
        """Writes must be JSON sent by this page: browsers cannot send that cross-site without permission."""
        origin = self.headers.get("Origin")
        if origin and not self.same_origin(origin):
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() == "application/json"

    def guard(self):
        if not self.host_ok():
            self.send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "unknown host"})
            return False
        return True

    # -- static files: allowlist only
    def list_directory(self, path):
        self.not_found()
        return None

    def static_allowed(self, p):
        if any(seg.startswith(".") or seg in ("history", "__pycache__") for seg in p.split("/")):
            return False
        if not p.endswith(STATIC_TYPES):
            return False
        if p.startswith(PUBLIC_PREFIXES):
            return True
        if p.startswith(PRIVATE_FILES):
            return self.trusted()
        return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.guard():
            return
        raw = urlparse(self.path).path
        p = posixpath.normpath(unquote(raw))
        if raw.endswith("/") and p != "/":
            p += "/"
        if p in ("/", "/gui", "/gui/"):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/gui/request_form.html")
            self.end_headers()
            return
        if not p.startswith("/api/"):
            if ".." in raw or "\\" in unquote(raw) or not self.static_allowed(p):
                return self.not_found()
            self.path = p
            return super().do_GET()
        u = self.user()
        q = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}
        if p == "/api/data":
            return self.send_json(200, {n: {"private": data_file(n, "private").exists() and self.trusted(),
                                            "synthetic": data_file(n, "synthetic").exists(),
                                            "default": self.set_for(n, None)} for n in DATASETS})
        m = re.fullmatch(r"/api/data/(equipment|parts)", p)
        if m:
            which = self.set_for(m[1], q.get("set"))
            if not which:
                return self.send_json(401, {"error": "Sign in to see the lab's private data."})
            d = read_json(data_file(m[1], which), None)
            return self.send_json(200, {"set": which, "data": d}) if d is not None else self.not_found()
        if p in ("/api/equipment/find", "/api/equipment/check"):
            which = self.set_for("equipment", q.get("set"))
            if not which:
                return self.send_json(401, {"error": "Sign in to see the lab's private data."})
            try:
                db = equipment_db.load(which)
            except FileNotFoundError:
                return self.not_found()
            if p.endswith("find"):
                return self.send_json(200, equipment_db.find(q.get("q", "")[:200], db))
            num = lambda k: float(q[k]) if q.get(k) not in (None, "") else None  # noqa: E731
            try:
                tmin, tmax = num("temp_min_c"), num("temp_max_c")
                temp = None if tmin is None and tmax is None else (tmin if tmin is not None else tmax, tmax if tmax is not None else tmin)
                req = {k: num(k) for k in ("force_n", "current_a", "voltage_kv", "frequency_hz", "sine_accel_gpk", "random_accel_grms", "rh_pct", "sample_mm")}
            except ValueError:
                return self.send_json(400, {"error": "numbers only"})
            return self.send_json(200, equipment_db.check(q.get("id", "")[:80], db, temp_c=temp, **req))
        if p == "/api/assistant/status":
            if not self.trusted():
                return self.send_json(401, {"error": "sign in"})
            from assistant import chat
            return self.send_json(200, chat.status())
        if p in ("/api/feedback", "/api/feedback/meta"):
            if not self.trusted():
                return self.send_json(401, {"error": "Sign in to give or see feedback from another device."})
            from assistant import feedback
            if p.endswith("meta"):
                return self.send_json(200, {**feedback.meta(), "can_manage": self.can_manage_feedback(), "by": self.feedback_by()})
            path = self.feedback_path()
            synthetic = not path.exists() and feedback.SYNTHETIC.exists()     # a fresh or public copy: show the format
            items = feedback.entries(feedback.SYNTHETIC if synthetic else path)
            if not self.can_manage_feedback() and not synthetic:
                items = [e for e in items if e.get("by") == self.feedback_by()]
            if q.get("format") == "csv":
                return self.send_text(200, feedback.to_csv(items), "text/csv; charset=utf-8", f"lab_request_feedback_{time.strftime('%Y%m%d')}.csv")
            return self.send_json(200, {"items": items, "summary": feedback.summary(items), "synthetic": synthetic,
                                        "can_manage": self.can_manage_feedback() and not synthetic})
        if p == "/api/me":
            info = {"user": u, "admin": self.is_admin(), "register": self.can_register(), "local": self.client_is_local()}
            return self.send_json(200 if u else 401, info)
        if not u:
            return self.send_json(401, {"error": "sign in"})
        if p == "/api/drafts":
            out = []
            for f in sorted((DRAFTS / u).glob("*.json")):
                d = read_json(f, None)
                if isinstance(d, dict):
                    out.append({k: d.get(k) for k in ("id", "form", "title", "created", "updated")})
            return self.send_json(200, sorted(out, key=lambda d: d.get("updated") or "", reverse=True))
        m = re.fullmatch(r"/api/drafts/([a-f0-9]{32})", p)
        if m:
            d = read_json(DRAFTS / u / f"{m[1]}.json", None)
            return self.send_json(200, d) if d else self.not_found()
        self.not_found()

    def do_POST(self):
        if not self.guard():
            return
        p = urlparse(self.path).path
        if not self.write_allowed():
            return self.send_json(403, {"error": "Only JSON requests from this page are accepted."})
        try:
            b = self.body()
        except Exception:
            return self.send_json(400, {"error": "bad request"})
        client = self.client_address[0]
        if p in ("/api/login", "/api/register"):
            name = str(b.get("user", "")).strip().lower()
            pw = str(b.get("password", ""))
            wait = locked_out(client, name)
            if wait:
                return self.send_json(429, {"error": f"Too many failed sign-ins. Try again in {wait // 60 + 1} minutes."})
            if not USER_RE.match(name) or not 8 <= len(pw) <= 256:
                return self.send_json(400, {"error": "User name: 2-32 letters, digits, . _ -. Password: 8 to 256 characters."})
            with LOCK:
                users = read_json(USERS, {})
                if p == "/api/register":
                    if not self.can_register():
                        return self.send_json(403, {"error": "New accounts are turned off on this server. Ask the admin."})
                    recent = [t for t in REGISTRATIONS.get(client, []) if time.time() - t < 3600]
                    if len(recent) >= 5:
                        return self.send_json(429, {"error": "Too many new accounts from this device. Try later."})
                    if name in users:
                        return self.send_json(409, {"error": "That user name is taken."})
                    first_local = not users and self.client_is_local()
                    users[name] = {**hash_password(pw), "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "sv": 0, "admin": first_local}
                    write_atomic(USERS, users)
                    REGISTRATIONS[client] = recent + [time.time()]
                elif name not in users or not check_password(users[name], pw):
                    note_failure(client, name)
                    time.sleep(0.5)
                    return self.send_json(401, {"error": "Wrong user name or password."})
                FAILS.pop((client, name), None)
                sv = users[name].get("sv", 0)
            return self.send_json(200, {"user": name, "admin": bool(users[name].get("admin"))}, cookie=self.cookie(make_token(name, sv), SESSION_DAYS * 86400))
        if p == "/api/logout":
            u = self.user()
            if u:
                with LOCK:
                    users = read_json(USERS, {})
                    if u in users:
                        users[u]["sv"] = users[u].get("sv", 0) + 1     # ends this account's sessions everywhere
                        write_atomic(USERS, users)
            return self.send_json(200, {"user": None}, cookie=self.cookie("", 0))
        if p == "/api/assistant":
            # Chat that drafts the request (assistant/chat.py). Same trust rule as Check quality; one turn at a time,
            # because the local model serves one request at a time.
            if not self.trusted():
                return self.send_json(401, {"error": "Sign in to use the assistant from another device."})
            msg, hist, form, fields = b.get("message"), b.get("history") or [], b.get("form"), b.get("fields") or {}
            if not isinstance(msg, str) or not msg.strip() or not isinstance(hist, list) or not isinstance(fields, dict):
                return self.send_json(400, {"error": "message, history and fields required"})
            hist = [{"role": h.get("role"), "content": str(h.get("content", ""))[:4000]} for h in hist[-12:] if isinstance(h, dict)]
            if not ASSISTANT_LOCK.acquire(blocking=False):
                return self.send_json(429, {"error": "The assistant is answering another request. Try again in a moment."})
            try:
                from assistant import chat
                pick = b.get("model") if isinstance(b.get("model"), str) else None     # checked against the allowed list
                return self.send_json(200, chat.assist(msg[:4000], hist, form, fields, model=(pick or "")[:80] or None))
            except Exception as e:
                print(f"[assistant] error: {type(e).__name__}: {e}", file=sys.stderr)
                return self.send_json(500, {"error": "The assistant hit an error; see the server window. Your draft is unchanged."})
            finally:
                ASSISTANT_LOCK.release()
        if p in ("/api/feedback", "/api/feedback/status"):
            if not self.trusted():
                return self.send_json(401, {"error": "Sign in to give feedback from another device."})
            from assistant import feedback
            if p.endswith("status"):
                if not self.can_manage_feedback():
                    return self.send_json(403, {"error": "Only admins (or the server computer) set feedback status."})
                ev, err = feedback.set_status(b.get("id"), b.get("status"), self.feedback_by(), b.get("note", ""), self.feedback_path())
                return self.send_json(400 if err else 200, {"error": err} if err else ev)
            recent = [t for t in FEEDBACK_SENT.get(client, []) if time.time() - t < 3600]
            if len(recent) >= 200:
                return self.send_json(429, {"error": "Too much feedback from this device in the last hour. Try later."})
            import lrt_version
            entry, err = feedback.clean(b, self.feedback_by(), {"server_version": lrt_version.text()})
            if err:
                return self.send_json(400, {"error": err})
            feedback.append(entry, self.feedback_path())
            FEEDBACK_SENT[client] = recent + [time.time()]
            return self.send_json(200, {"saved": entry["id"], "screen": entry["screen"]})
        if p == "/api/quality":
            if not self.trusted():
                return self.send_json(401, {"error": "Sign in to use Check quality from another device."})
            from assistant import quality
            form = b.get("form")
            if form not in quality.SCHEMA["forms"] or not isinstance(b.get("fields"), dict):
                return self.send_json(400, {"error": "form and fields required"})
            return self.send_json(200, quality.review(form, b["fields"]))
        self.not_found()

    def do_PUT(self):
        if not self.guard():
            return
        p = urlparse(self.path).path
        if not self.write_allowed():
            return self.send_json(403, {"error": "Only JSON requests from this page are accepted."})
        u = self.user()
        m = re.fullmatch(r"/api/data/(equipment|parts)", p)
        if m:
            if not u:
                return self.send_json(401, {"error": "Sign in to edit lab data."})
            if not self.is_admin():
                return self.send_json(403, {"error": "Only admins edit lab data. On the server computer run: python gui/serve.py --make-admin " + u})
            which = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}.get("set") or ("private" if data_file(m[1], "private").exists() else "synthetic")
            if which not in ("private", "synthetic"):
                return self.send_json(400, {"error": "set must be private or synthetic"})
            try:
                d = self.body()
            except Exception:
                return self.send_json(400, {"error": "bad request"})
            errs = validate_dataset(m[1], d)
            if errs:
                return self.send_json(422, {"error": "Not saved: fix these first.", "problems": errs[:20]})
            f = data_file(m[1], which)
            with LOCK:
                if f.exists():   # keep the previous version, so an edit can always be undone
                    hist = f.parent / "history" / f"{f.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{u}.json"
                    hist.parent.mkdir(parents=True, exist_ok=True)
                    hist.write_bytes(f.read_bytes())
                d.setdefault("_meta", {}).update(last_edit=time.strftime("%Y-%m-%dT%H:%M:%S"), last_editor=u)
                write_atomic(f, d)
            return self.send_json(200, {"saved": m[1], "set": which, "updated": d["_meta"]["last_edit"]})
        m = re.fullmatch(r"/api/drafts/([a-f0-9]{32})", p)
        if not m:
            return self.not_found()
        if not u:
            return self.send_json(401, {"error": "sign in"})
        try:
            d = self.body()
        except Exception:
            return self.send_json(400, {"error": "bad request"})
        target = DRAFTS / u / f"{m[1]}.json"
        if not target.exists() and len(list((DRAFTS / u).glob("*.json"))) >= MAX_DRAFTS_PER_USER:
            return self.send_json(507, {"error": f"Draft limit ({MAX_DRAFTS_PER_USER}) reached. Delete old drafts."})
        d.update(id=m[1], owner=u, updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with LOCK:
            write_atomic(target, d)
        self.send_json(200, {"id": m[1], "updated": d["updated"]})

    def do_DELETE(self):
        if not self.guard():
            return
        p = urlparse(self.path).path
        u = self.user()
        m = re.fullmatch(r"/api/drafts/([a-f0-9]{32})", p)
        if not m or not u or not self.write_allowed_for_delete():
            return self.not_found()
        with LOCK:
            (DRAFTS / u / f"{m[1]}.json").unlink(missing_ok=True)
        self.send_json(200, {"deleted": m[1]})

    def write_allowed_for_delete(self):
        origin = self.headers.get("Origin")
        return (not origin or self.same_origin(origin)) and \
            self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")


def set_admin(name, value):
    users = read_json(USERS, {})
    if name not in users:
        sys.exit(f"[gui] no account '{name}'. Accounts: {', '.join(sorted(users)) or 'none'}")
    users[name]["admin"] = value
    write_atomic(USERS, users)
    print(f"[gui] {name} is {'now' if value else 'no longer'} an admin.")


def main():
    ap = argparse.ArgumentParser(description="Local server for the request forms (see SECURITY.md)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--allow-lan", action="store_true", help="also accept devices on the local network (inbound only)")
    ap.add_argument("--allow-register", action="store_true", help="with --allow-lan: let new accounts be created from the network")
    ap.add_argument("--no-register", action="store_true", help="turn off creating accounts from the page")
    ap.add_argument("--allow-host", action="append", default=[], help="extra host name the browser may use, e.g. mypc.local:8010")
    ap.add_argument("--tls-cert"), ap.add_argument("--tls-key")
    ap.add_argument("--make-admin"), ap.add_argument("--remove-admin")
    ap.add_argument("--colab", action="store_true", help="Google Colab: accept the notebook's proxy. SYNTHETIC data only")
    a = ap.parse_args()
    if a.make_admin or a.remove_admin:
        return set_admin((a.make_admin or a.remove_admin).lower(), bool(a.make_admin))
    host = "0.0.0.0" if a.allow_lan else a.host
    if host not in LOOPBACK and not a.allow_lan:
        sys.exit(f"[gui] refusing to listen on {host}: this suite is local only. Use --allow-lan to open it to your network.")
    Handler.lan = a.allow_lan
    Handler.port = a.port
    Handler.register_local = not a.no_register
    Handler.allow_register = not a.no_register and (not a.allow_lan or a.allow_register)
    Handler.extra_hosts = {h.lower() for h in a.allow_host}
    if a.colab:
        if a.allow_lan or host not in LOOPBACK:
            sys.exit("[gui] --colab listens on 127.0.0.1 only; it cannot be combined with --allow-lan.")
        if private_data_present():
            sys.exit("[gui] --colab refused: data/private holds files. Colab is Google's cloud; use SYNTHETIC data only.")
        Handler.colab = True
        Handler.register_local = Handler.allow_register = False     # guests only: drafts stay in the browser
        print("[gui] Colab mode: Google's notebook proxy is accepted; SYNTHETIC data only.", flush=True)
    srv = http.server.ThreadingHTTPServer((host, a.port), functools.partial(Handler, directory=str(ROOT)))
    scheme = "http"
    if a.tls_cert and a.tls_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(a.tls_cert, a.tls_key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        Handler.tls, scheme = True, "https"
    print(f"[gui] {scheme}://127.0.0.1:{a.port}/gui/request_form.html" + ("  (also on your network)" if a.allow_lan else "  (this computer only)"), flush=True)
    if a.allow_lan and not Handler.tls:
        print("[gui] warning: on the network without --tls-cert, sign-in cookies travel unencrypted. Use it only on a trusted network.", flush=True)
    if a.allow_lan:
        print(f"[gui] new accounts from other devices: {'on' if Handler.allow_register else 'off'} (this computer: {'on' if Handler.register_local else 'off'})", flush=True)
    import lrt_pidfile
    lrt_pidfile.write("serve", a.port)          # stop.bat uses it
    srv.serve_forever()


if __name__ == "__main__":
    main()
