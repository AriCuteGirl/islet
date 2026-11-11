"""Islet model: config, sounds, agent event parsing. No GTK here."""
import collections
import re
import json
import math
import os
import struct
import time
import wave

import pets as pip
from islet import CONF, DATA

COLORS = {
    "idle": (0.62, 0.62, 0.68),
    "working": (1.0, 0.60, 0.24),
    "question": (1.0, 0.80, 0.27),
    "done": (0.62, 0.90, 0.42),
}
MOOD_FOR = {"idle": "sleepy", "working": "focus", "question": "curious", "done": "happy"}
NO_BLOCK_TOOLS = {"AskUserQuestion", "ExitPlanMode", "EnterPlanMode"}
SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command", "unified_exec", "container.exec"}
SOURCES = {"claude": "Claude Code", "codex": "Codex", "hyprclick": "hyprclick",
           "steam": "Steam downloads", "downloads": "Browser downloads", "updates": "System updates",
           "actions": "Script buttons", "nowplaying": "Game / now playing in the pill"}
ACCENTS = ["#9be36b", "#ff9a3c", "#7aa2ff", "#c79bff", "#ff7eb6", "#66d9e8"]
DEFAULT_CONF = {
    "apps": {}, "custom": [], "actions": [], "pet": "pup", "accent": "#9be36b", "margin_top": 6, "x": None,
    "sound": True, "desktop_notify": False, "monitor": None, "done_linger": 12, "timer_min": 25,
    "upd_every_h": 3, "auto_update": False, "auto_hour": 20, "auto_min": 0, "auto_mode": 0, "last_auto": "",
    "terminal": "", "names": {}, "pet_names": {"pup": "Puppy", "kitty": "Kitty"},
    "welcome": True, "user_name": "",
}


def hex_rgb(h):
    h = str(h or "#9a9aa6").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.6, 0.6, 0.65)


def load_conf():
    c = dict(DEFAULT_CONF)
    try:
        with open(CONF) as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return c


def save_conf(c):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as f:
        json.dump(c, f, indent=2)


# --------------------------------------------------------------------------- sounds

def _tone_wav(path, notes, dur=0.16, gap=0.07, vol=0.32):
    rate = 44100
    frames = bytearray()
    total = (dur + gap) * len(notes) + 0.5
    n = int(total * rate)
    buf = [0.0] * n
    for i, f in enumerate(notes):
        start = int(i * (dur + gap) * rate)
        for k in range(int(0.9 * rate)):
            if start + k >= n:
                break
            tt = k / rate
            env = math.exp(-tt * 6.0) * min(1.0, tt * 200)
            buf[start + k] += env * (math.sin(2 * math.pi * f * tt) + 0.25 * math.sin(4 * math.pi * f * tt))
    peak = max(1e-6, max(abs(x) for x in buf))
    for x in buf:
        frames += struct.pack("<h", int(x / peak * vol * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def ensure_assets():
    sd = os.path.join(DATA, "sounds")
    os.makedirs(sd, exist_ok=True)
    if not os.path.exists(os.path.join(sd, "done.wav")):
        _tone_wav(os.path.join(sd, "done.wav"), [1046.5, 1318.5, 1568.0])
    if not os.path.exists(os.path.join(sd, "hello.wav")):
        _tone_wav(os.path.join(sd, "hello.wav"), [523.25, 659.25, 783.99, 1046.5], dur=0.13, gap=0.05, vol=0.28)
    if not os.path.exists(os.path.join(sd, "ask.wav")):
        _tone_wav(os.path.join(sd, "ask.wav"), [784.0, 1046.5], dur=0.12)
    for sp in pip.PETS:
        p = os.path.join(DATA, f"{sp}.png")
        if not os.path.exists(p):
            pip.render_png(p, species=sp)


# --------------------------------------------------------------------------- event model

def _base(p):
    p = str(p or "").rstrip("/")
    return os.path.basename(p) or p


def _first_line(s, n=90):
    s = str(s or "").strip().splitlines()
    s = s[0] if s else ""
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(tool, inp, perm=False):
    inp = inp if isinstance(inp, dict) else {}
    t = tool or "tool"
    cmd = inp.get("command", inp.get("cmd"))
    if t in SHELL_TOOLS or (cmd is not None and t not in ("Task", "Agent")):
        if isinstance(cmd, list):
            cmd = " ".join(str(x) for x in cmd)
            if cmd.startswith("bash -lc ") or cmd.startswith("bash -c "):
                cmd = cmd.split(" ", 2)[2]
        return _first_line(cmd) if perm else "$ " + _first_line(cmd)
    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    verbs = {"Read": "read", "Write": "write", "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit"}
    if t in verbs:
        v = verbs[t]
        return f"{v} {_base(fp)}" if perm else f"{ {'read': 'Reading', 'write': 'Writing', 'edit': 'Editing'}[v]} {_base(fp)}"
    if t == "apply_patch":
        patch = str(inp.get("input") or inp.get("patch") or "")
        files = [ln.split(":", 1)[1].strip() for ln in patch.splitlines() if ln.startswith("*** ") and "File:" in ln]
        name = ", ".join(_base(f) for f in files[:2]) or "files"
        return f"patch {name}" if perm else f"Patching {name}"
    if t == "Grep":
        return f"Searching “{_first_line(inp.get('pattern'), 40)}”"
    if t == "Glob":
        return f"Finding {_first_line(inp.get('pattern'), 40)}"
    if t == "WebFetch":
        u = str(inp.get("url", ""))
        host = u.split("//", 1)[-1].split("/", 1)[0]
        return f"fetch {host}" if perm else f"Fetching {host}"
    if t == "WebSearch":
        return f"Searching web: {_first_line(inp.get('query'), 50)}"
    if t in ("Task", "Agent"):
        return f"Agent: {_first_line(inp.get('description') or inp.get('prompt'), 60)}"
    if t in ("TodoWrite", "update_plan"):
        return "Updating plan"
    if t.startswith("mcp__"):
        parts = t.split("__")
        srv = parts[1] if len(parts) > 1 else "mcp"
        name = parts[-1]
        return f"{srv}: {name}"
    return f"use {t}" if perm else t


def last_assistant_text(ev):
    for k in ("last_assistant_message", "last-assistant-message"):
        if ev.get(k):
            return str(ev[k])
    path = ev.get("transcript_path")
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 300_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for ln in reversed(lines):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        msg = o.get("message") if isinstance(o, dict) else None
        if o.get("type") == "assistant" and isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                if any(t.strip() for t in texts):
                    return "\n".join(texts).strip()
        # codex rollout format
        p = o.get("payload") if isinstance(o, dict) else None
        if isinstance(p, dict) and p.get("type") == "message" and p.get("role") == "assistant":
            texts = [c.get("text", "") for c in p.get("content", []) if isinstance(c, dict)]
            if any(t.strip() for t in texts):
                return "\n".join(texts).strip()
    return ""


PROJECT_NAMES = {}  # filled from config "names" by the island


class Session:
    def __init__(self, sid, src, cwd):
        self.sid, self.src, self.cwd = sid, src, cwd
        self.state = "idle"
        self.text = "Started"
        self.answer = ""
        self.hist = collections.deque(maxlen=8)
        self.updated = time.time()
        self.done_at = 0.0
        self.code = None  # last code change, for the live code view

    @property
    def project(self):
        """The project folder's name, or the display name set in config "names" (by path or folder name)."""
        return PROJECT_NAMES.get(self.cwd.rstrip("/")) or PROJECT_NAMES.get(_base(self.cwd)) \
            or _base(self.cwd) or "session"

    @property
    def agent(self):
        return "Codex" if self.src == "codex" else "Claude Code"

    def log(self, text, state=None):
        self.text = text
        if state:
            self.state = state
        self.updated = time.time()
        self.hist.append((time.strftime("%H:%M"), text))


class Pending:
    _n = 0

    def __init__(self, conn, sess, label):
        Pending._n += 1
        self.id = Pending._n
        self.conn, self.sess, self.label = conn, sess, label


# --------------------------------------------------------------------------- widgets


def pet_phrase(text):
    """Session text ("Editing lag.rs", "$ npm test", ...) as what the pet is doing."""
    t = text or ""
    low = t[:1].lower() + t[1:]
    for pre, verb in (("Thinking", "is thinking…"), ("Session started", "is ready"), ("Done", "is done ✓"),
                      ("Answered in terminal", "is back to work"), ("Has a question", "has a question for you"),
                      ("Updating plan", "is planning")):
        if t.startswith(pre):
            return verb
    if t.startswith("$ "):
        return "is running " + t[2:]
    if t.startswith("Agent: "):
        return "sent a helper: " + t[7:]
    if t.startswith("Allowed: ") or t.startswith("Denied: "):
        return ("got the OK: " if t.startswith("Allowed") else "was told no: ") + t.split(": ", 1)[1]
    m = re.match(r"(Reading|Editing|Writing|Patching|Searching|Finding|Fetching)\b(.*)", t)
    if m:
        return "is " + m.group(1).lower() + m.group(2)
    if ": " in t and t.split(": ", 1)[0].isidentifier():  # mcp tools "server: tool"
        return "is using " + t
    return "is " + low if low else "is busy"


def user_name(conf):
    """What Islet calls you: Settings, else the account's display name, else the login name."""
    if (conf.get("user_name") or "").strip():
        return conf["user_name"].strip()
    import pwd
    p = pwd.getpwuid(os.getuid())
    return (p.pw_gecos.split(",")[0].strip() or p.pw_name).capitalize()


def greeting(hour=None):
    h = time.localtime().tm_hour if hour is None else hour
    return "Good morning" if 5 <= h < 12 else "Good afternoon" if h < 18 else "Good evening" if h < 23 else "Hey night owl"
