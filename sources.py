"""Built-in live activities: things Islet watches by itself (hyprclick + lagswitch, Steam,
browser downloads, and custom commands from Settings).

Each watcher calls post(app, id, activity_or_None). An activity is a dict:
  title, detail, color (hex), mood (pet mood), until (epoch secs, for countdowns),
  total (secs, for the bar), flash (True for short "it turned off" notes),
  progress (0..1 bar in the pill), pulse (bar with no known end), notify (chime + desktop note once)
Read-only: they only ask for status, same as the CLIs and hyprclick's overlay do.
"""
import glob
import os
import re
import socket
import subprocess
import threading
import time

LAGSWITCH_SOCK = "/run/lagswitch/sock"
HYPRCLICK_SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "hyprclick.sock")

FROZEN = "#78c8ff"
LAG = "#ff6b6b"
CLICK = "#c79bff"
AFK = "#8fe3c8"
OFF = "#9a9aa6"
FRIENDLY = {"org.vinegarhq.sober": "Roblox", "sober": "Roblox", "steam_app_0": "your game", "minecraft": "Minecraft"}
STEAM = "#66c0f4"
DL = "#ffd166"
CUSTOM = "#a0e0ff"


def ask(path, cmd, timeout=0.4):
    if not os.path.exists(path):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((cmd + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        return buf.decode("utf-8", "replace").strip()
    except OSError:
        return None


class LagswitchWatch:
    app = "hyprclick"  # lagswitch is hyprclick's Lag tab, so it shows as one app

    def __init__(self, post):
        self.post = post
        self.was_frozen = False
        self.was_lag = False
        self.total = 0.0

    def poll(self):
        reply = ask(LAGSWITCH_SOCK, "status")
        if reply is None or not reply.startswith("ok "):
            if self.was_frozen or self.was_lag:
                self.post(self.app, "freeze", None)
                self.post(self.app, "lag", None)
            self.was_frozen = self.was_lag = False
            return
        text = reply[3:]
        parts = text.split(" ")
        now = time.time()

        if parts[0] == "frozen" and len(parts) >= 5:
            mode, direction, left, target = parts[1], parts[2], parts[3], parts[4]
            what = "whole PC" if target == "network" else {"in": "incoming", "out": "outgoing"}.get(direction, "one app")
            act = {"title": "Frozen", "detail": what, "color": FROZEN, "mood": "dizzy"}
            if mode == "timed":
                secs = int(left) / 1000 if left.isdigit() else 0
                self.total = max(self.total, secs)
                act.update(until=now + secs, total=self.total)
            elif mode == "hold":
                act["detail"] += " · while held"
            self.post(self.app, "freeze", act)
            self.was_frozen = True
        else:
            self.total = 0.0
            if self.was_frozen:
                self.post(self.app, "freeze", {"title": "Unfrozen", "detail": "", "color": OFF, "mood": "happy",
                                               "until": now + 1.2, "flash": True})
            self.was_frozen = False

        if "lag" in parts:
            i = parts.index("lag")
            ms = parts[i + 1] if i + 1 < len(parts) else "?"
            field = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in parts if "=" in p}
            detail = f"choke {ms} ms" if field.get("style") == "choke" else f"+{ms} ms ping"
            if field.get("jitter") not in (None, "0"):
                detail += f" · jitter {field['jitter']}%"
            self.post(self.app, "lag", {"title": "Fake lag", "detail": detail, "color": LAG, "mood": "curious"})
            self.was_lag = True
        elif self.was_lag:
            self.post(self.app, "lag", {"title": "Fake lag off", "detail": "", "color": OFF, "mood": "happy",
                                        "until": now + 1.2, "flash": True})
            self.was_lag = False


class HyprclickWatch:
    app = "hyprclick"

    def __init__(self, post):
        self.post = post
        self.on = set()
        self.afk_left = None

    def _set(self, key, act):
        if act is None and key not in self.on:
            return
        (self.on.add if act else self.on.discard)(key)
        self.post(self.app, key, act)

    def poll(self):
        reply = ask(HYPRCLICK_SOCK, "status")
        if reply is None:
            self._set("clicker", None)
            self._set("afk", None)
            return
        if reply.startswith("running") or reply.startswith("paused"):
            paused = reply.startswith("paused")
            rest = reply.split(")", 1)[-1].strip() if paused else reply.split(" ", 1)[-1]
            # "123 clicks · 20 cps window ..." -> keep it as the detail
            self._set("clicker", {"title": "Clicker paused" if paused else "Clicking", "detail": rest,
                                  "color": OFF if paused else CLICK, "mood": "sleepy" if paused else "focus"})
        else:
            self._set("clicker", None)
        afk = ask(HYPRCLICK_SOCK, "afk")
        if afk and afk.startswith("on"):
            # "on · org.vinegarhq.Sober · gamepad · next ~7m"
            parts = [x.strip() for x in afk[2:].split("·") if x.strip()]
            nxt = next((x for x in parts if x.startswith("next")), "")
            target = next((x for x in parts if not x.startswith("next")), "your game")
            name = FRIENDLY.get(target.lower(), target.split(".")[-1])
            mins = re.search(r"~(\d+)m", nxt)
            left = int(mins.group(1)) if mins else 0 if "<1m" in nxt else None
            when = f"next wiggle in {left} min" if left else "wiggling soon" if left == 0 else ""
            self._set("afk", {"title": "{pet} is keeping you online", "detail": f"{name} · {when}".strip(" ·"),
                              "color": AFK, "mood": "focus"})
            # the countdown jumped back up: hyprclick just nudged the game
            if left is not None and self.afk_left is not None and left > self.afk_left + 1:
                self.post(self.app, f"nudge{time.time():.0f}", {
                    "title": f"{{pet}} wiggled {name} 🐾", "detail": f"You're still online · next in {left} min",
                    "color": AFK, "mood": "happy", "ttl": 6, "flash": True, "toast": True})
            self.afk_left = left
        else:
            self.afk_left = None
            self._set("afk", None)


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


class Rate:
    """Bytes per second over the last few seconds."""

    def __init__(self):
        self.pts = []

    def add(self, n, now):
        self.pts = [p for p in self.pts if now - p[1] < 6] + [(n, now)]
        (n0, t0), (n1, t1) = self.pts[0], self.pts[-1]
        return (n1 - n0) / (t1 - t0) if t1 - t0 > 0.5 and n1 >= n0 else 0.0


# ---------------------------------------------------------------- Steam

STEAM_ROOTS = ["~/.local/share/Steam", "~/.steam/steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam"]
UPDATE_RUNNING, UPDATE_PAUSED, UPDATE_STARTED, FULLY_INSTALLED = 256, 512, 1024, 4
_KV = re.compile(r'^\s*"([^"]+)"\s+"([^"]*)"', re.M)


def _vdf_top(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(65536)
    except OSError:
        return {}
    out = {}
    for k, v in _KV.findall(text):
        out.setdefault(k, v)
    return out


class SteamWatch:
    """Reads each library's appmanifest_*.acf (StateFlags + BytesDownloaded/BytesToDownload)."""
    app = "steam"

    def __init__(self, post):
        self.post = post
        self.root = next((os.path.expanduser(r) for r in STEAM_ROOTS
                          if os.path.isdir(os.path.expanduser(r) + "/steamapps")), None)
        self.mtimes = {}
        self.info = {}
        self.active = {}
        self.libs_at = 0
        self.libs = []

    def info_by_id(self, appid):
        return next((kv for kv in self.info.values() if kv.get("appid") == appid), None)

    def _libraries(self):
        if time.time() - self.libs_at > 60:
            self.libs_at = time.time()
            vdf = os.path.join(self.root, "steamapps", "libraryfolders.vdf")
            try:
                paths = re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="replace").read())
            except OSError:
                paths = []
            self.libs = [p for p in dict.fromkeys([self.root] + paths) if os.path.isdir(p + "/steamapps")]
        return self.libs

    def poll(self):
        if not self.root:
            return
        now = time.time()
        seen = set()
        for lib in self._libraries():
            for path in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
                seen.add(path)
                try:
                    m = os.stat(path).st_mtime
                except OSError:
                    continue
                if self.mtimes.get(path) != m:
                    self.mtimes[path] = m
                    self.info[path] = _vdf_top(path)
        for path in list(self.info):
            if path not in seen:
                self.info.pop(path)
        running = {}
        for path, kv in self.info.items():
            try:
                flags = int(kv.get("StateFlags", "0"))
            except ValueError:
                flags = 0
            if flags & (UPDATE_RUNNING | UPDATE_STARTED | UPDATE_PAUSED):
                running[kv.get("appid", path)] = (kv, flags)
        for appid, (kv, flags) in list(running.items()):
            paused = bool(flags & UPDATE_PAUSED) and not flags & UPDATE_RUNNING
            if paused and appid not in self.active:
                running.pop(appid)  # queued/paused before we looked: not something happening now
                continue
            st = self.active.setdefault(appid, {"rate": Rate(), "since": now, "name": kv.get("name", appid)})
            name = st["name"]
            todo, done = int(kv.get("BytesToDownload", 0) or 0), int(kv.get("BytesDownloaded", 0) or 0)
            stage, staged = int(kv.get("BytesToStage", 0) or 0), int(kv.get("BytesStaged", 0) or 0)
            verb = "Updating" if flags & FULLY_INSTALLED else "Downloading"
            act = {"title": f"{'Paused' if paused else verb} {name}", "color": STEAM if not paused else OFF,
                   "mood": "sleepy" if paused else "focus"}
            if todo and done < todo:
                speed = st["rate"].add(done, now)
                act["progress"] = done / todo
                act["detail"] = f"{done * 100 // todo}% · {human(done)} / {human(todo)}" + (f" · {human(speed)}/s" if speed and not paused else "")
            elif stage and staged < stage:
                act["progress"] = staged / stage
                act["detail"] = f"installing {staged * 100 // stage}%"
            else:
                act["pulse"] = True
                act["detail"] = "starting" if not done else "finishing"
            self.post(self.app, appid, act)
        for appid in [a for a in self.active if a not in running]:
            st = self.active.pop(appid)
            self.post(self.app, appid, None)
            kv = self.info_by_id(appid)
            if now - st["since"] > 3 and kv and int(kv.get("StateFlags", "0") or 0) & FULLY_INSTALLED:
                self.post(self.app, appid + ":done", {"title": f"{st['name']} is ready", "detail": "Steam",
                                                       "color": STEAM, "mood": "happy", "ttl": 6, "flash": True,
                                                       "notify": True})


def steam_app_name(appid):
    for root in STEAM_ROOTS:
        root = os.path.expanduser(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            libs = re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="replace").read())
        except OSError:
            continue
        for lib in [root] + libs:
            kv = _vdf_top(os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf"))
            if kv.get("name"):
                return kv["name"]
    return None


SKIP_APPIDS = {"0", "228980", "1070560", "1391110", "1493710", "1628350", "2180100"}  # redists, runtimes, Proton


def running_game():
    """(key, name) of the game being played: a Steam game (SteamAppId in its environment) or Roblox (Sober)."""
    uid = os.getuid()
    found = None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            comm = open(f"/proc/{pid}/comm").read().strip()
            if comm == "sober":
                return ("roblox", "Roblox")
            env = open(f"/proc/{pid}/environ", "rb").read()
        except OSError:
            continue
        for key in (b"SteamAppId=", b"STEAM_COMPAT_APP_ID="):
            j = env.find(key)
            if j >= 0:
                appid = env[j + len(key): env.find(b"\0", j)].decode(errors="replace")
                if appid.isdigit() and appid not in SKIP_APPIDS:
                    found = found or appid
                break
    if found:
        return (found, steam_app_name(found) or f"Steam game {found}")
    return None


# ---------------------------------------------------------------- browser downloads

PART_EXT = (".part", ".crdownload", ".partial", ".download", ".opdownload")


def _download_dirs():
    dirs = []
    try:
        for line in open(os.path.expanduser("~/.config/user-dirs.dirs"), encoding="utf-8"):
            if line.startswith("XDG_DOWNLOAD_DIR="):
                dirs.append(os.path.expandvars(line.split("=", 1)[1].strip().strip('"')))
    except OSError:
        pass
    dirs.append(os.path.expanduser("~/Downloads"))
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


class DownloadsWatch:
    """In-progress browser downloads (*.part, *.crdownload, ...) in the Downloads folder."""
    app = "downloads"

    def __init__(self, post):
        self.post = post
        self.dirs = _download_dirs()
        self.active = {}

    def poll(self):
        now = time.time()
        found = {}
        for d in self.dirs:
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if not e.name.endswith(PART_EXT) or not e.is_file():
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                if now - st.st_mtime > 20:
                    continue  # leftover from a crashed or paused download
                final = e.name[: e.name.rfind(".")]
                found[e.path] = (final, st.st_size, d)
        for path, (final, size, d) in found.items():
            st = self.active.setdefault(path, {"rate": Rate(), "since": now, "final": os.path.join(d, final), "name": final})
            speed = st["rate"].add(size, now)
            self.post(self.app, path, {"title": "Downloading", "detail": f"{final} · {human(size)}" + (f" · {human(speed)}/s" if speed else ""),
                                       "color": DL, "mood": "focus", "pulse": True})
        for path in [p for p in self.active if p not in found]:
            st = self.active.pop(path)
            self.post(self.app, path, None)
            if os.path.exists(st["final"]) and os.path.getsize(st["final"]) > 0:
                self.post(self.app, path + ":done", {"title": "Downloaded", "detail": st["name"], "color": DL,
                                                     "mood": "happy", "ttl": 5, "flash": True, "notify": True})


# ---------------------------------------------------------------- custom commands

class CommandWatch(threading.Thread):
    """Runs the user's own commands from Settings. First output line is shown; empty hides it.
    A leading "42%" fills the progress bar."""

    def __init__(self, post, get_custom, enabled):
        super().__init__(daemon=True)
        self.post, self.get_custom, self.enabled = post, get_custom, enabled
        self.next = {}
        self.shown = set()

    def run(self):
        while True:
            now = time.time()
            items = {c["name"]: c for c in self.get_custom() if c.get("name") and c.get("cmd")}
            for name in [n for n in self.shown if n not in items or not self.enabled(n)]:
                self.shown.discard(name)
                self.post(name, "cmd", None)
            for name, c in items.items():
                if not self.enabled(name) or now < self.next.get(name, 0):
                    continue
                self.next[name] = now + max(1.0, float(c.get("every") or 2))
                try:
                    out = subprocess.run(["sh", "-c", c["cmd"]], capture_output=True, text=True, timeout=10).stdout
                except (OSError, subprocess.SubprocessError):
                    out = ""
                line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
                if not line:
                    if name in self.shown:
                        self.shown.discard(name)
                        self.post(name, "cmd", None)
                    continue
                act = {"title": name, "detail": line[:120], "color": c.get("color") or CUSTOM, "mood": "focus"}
                m = re.match(r"^(\d{1,3}(?:\.\d+)?)%\s*(.*)$", line)
                if m:
                    act["progress"] = min(100.0, float(m.group(1))) / 100
                    act["detail"] = (m.group(2) or f"{m.group(1)}%")[:120]
                    if m.group(2):
                        act["detail"] = f"{m.group(1)}% · {m.group(2)}"[:120]
                self.shown.add(name)
                self.post(name, "cmd", act)
            time.sleep(0.5)


class Watchers(threading.Thread):
    def __init__(self, post, enabled):
        super().__init__(daemon=True)
        self.enabled = enabled  # callable(app) -> bool
        self.lag = LagswitchWatch(post)
        self.click = HyprclickWatch(post)
        self.steam = SteamWatch(post)
        self.downloads = DownloadsWatch(post)

    def run(self):
        n = 0
        while True:
            if self.enabled("hyprclick"):
                self.lag.poll()
                if n % 4 == 0:
                    self.click.poll()
            if n % 7 == 0:
                for name, w in (("steam", self.steam), ("downloads", self.downloads)):
                    if self.enabled(name):
                        try:
                            w.poll()
                        except Exception as e:  # a watcher bug must not stop the others
                            print(f"islet: {name} watcher: {e}")
                    elif w.active:
                        for key in list(w.active):
                            w.active.pop(key)
                            w.post(w.app, key, None)
            n += 1
            time.sleep(0.15)
