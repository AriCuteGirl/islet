"""Script buttons: run your own scripts (like vr-up) from the island and follow their output."""
import os
import re
import shlex
import signal
import subprocess
import threading
import time

LOGDIR = os.path.expanduser("~/.cache/islet/actions")
BIN_DIRS = ["~/.local/bin", "~/bin"]
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")
COLOR = "#ffcf5c"


def nice_name(cmd):
    first = shlex.split(cmd)[0] if cmd.strip() else cmd
    base = os.path.basename(first)
    return re.sub(r"\.(sh|py|bash)$", "", base) or base


def find_scripts(skip=()):
    """Executables in ~/.local/bin and ~/bin, minus backups and ones already added."""
    out = []
    for d in BIN_DIRS:
        d = os.path.expanduser(d)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.startswith(".") or ".bak" in n or n.endswith((".old", "~")) or p in skip or n in skip:
                continue
            if os.path.isfile(p) and os.access(p, os.X_OK) and os.path.getsize(p) < 2_000_000:
                out.append(p)
    return out


class Runner:
    def __init__(self, post, alert):
        self.post = post      # post(app, id, activity) from any thread (already GLib-safe)
        self.alert = alert    # alert(kind, title, body) from any thread (already GLib-safe)
        self.procs = {}
        self.lines = {}

    def running(self, name):
        p = self.procs.get(name)
        return p is not None and p.poll() is None

    def toggle(self, action):
        if self.running(action["name"]):
            self.stop(action["name"])
        else:
            self.start(action)

    def start(self, action):
        name, cmd = action["name"], action["cmd"]
        os.makedirs(LOGDIR, exist_ok=True)
        path = os.path.join(LOGDIR, re.sub(r"[^\w.-]", "_", name) + ".log")
        # Output goes to a file, not a pipe: scripts like vr-up leave programs running that
        # inherit stdout, and a closed pipe would kill them with SIGPIPE.
        try:
            with open(path, "wb") as out:
                p = subprocess.Popen(["bash", "-lc", cmd], stdout=out, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True, cwd=os.path.expanduser("~"))
        except OSError as e:
            self.post("actions", name, {"title": f"{name} failed", "detail": str(e), "color": "#ff6b6b",
                                        "mood": "curious", "ttl": 6, "flash": True})
            return
        self.procs[name] = p
        self.lines[name] = []
        self.post("actions", name, {"title": name, "detail": "starting…", "color": COLOR, "mood": "focus", "pulse": True})
        threading.Thread(target=self._follow, args=(name, p, path), daemon=True).start()

    def stop(self, name):
        p = self.procs.get(name)
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def _follow(self, name, p, path):
        started = time.time()
        pos, partial = 0, b""
        while True:
            done = p.poll() is not None
            try:
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except OSError:
                chunk = b""
            if chunk:
                parts = (partial + chunk).split(b"\n")
                partial = parts.pop()
                buf = self.lines[name]
                for raw in parts:
                    line = ANSI.sub("", raw.decode("utf-8", "replace")).strip()
                    if line:
                        buf.append(line)
                del buf[:-6]
                if buf:
                    self.post("actions", name, {"title": name, "detail": buf[-1][:110], "color": COLOR,
                                                "mood": "focus", "pulse": True, "lines": list(buf)})
            if done:
                break
            time.sleep(0.3)
        code = p.wait()
        took = time.time() - started
        last = (self.lines.get(name) or [""])[-1][:110]
        if code == 0:
            act = {"title": f"{name} done", "detail": last or f"{took:.0f}s", "color": "#9be36b", "mood": "happy"}
        elif code < 0 or code in (143, 130):
            act = {"title": f"{name} stopped", "detail": last, "color": "#9a9aa6", "mood": "sleepy"}
        else:
            act = {"title": f"{name} failed (exit {code})", "detail": last, "color": "#ff6b6b", "mood": "curious"}
        self.post("actions", name, dict(act, ttl=8, flash=True, lines=list(self.lines.get(name, []))))
        if code >= 0 and took > 3:
            self.alert("done" if code == 0 else "ask", act["title"], last)
