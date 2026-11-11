"""System updates: counts pending pacman (checkupdates), AUR (yay -Qua) and Flatpak updates,
and runs updates in a terminal (pacman/yay need your password) or Flatpak silently."""
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time

AUTO_MODES = ["Everything, in a terminal", "Flatpak only, silent"]
EVERY_H = [1, 3, 6, 12, 24]
CACHE = os.path.expanduser("~/.cache/islet/updates.json")
TERMINALS = ["kitty", "alacritty", "foot", "ghostty", "konsole", "wezterm", "xterm"]


def _lines(cmd, timeout=180):
    if not shutil.which(cmd[0]):
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    # checkupdates exits 2 when there is nothing to update; 1 when its temp database is busy
    if r.returncode not in (0, 2):
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def terminal_cmd(conf, script):
    term = conf.get("terminal") or next((t for t in TERMINALS if shutil.which(t)), None)
    if not term:
        return None
    if term in ("konsole", "xterm"):
        return [term, "-e", "sh", "-c", script]
    if term == "foot":
        return [term, "--title", "Islet updates", "sh", "-c", script]
    if term == "ghostty":
        return [term, "-e", "sh", "-c", script]
    if term == "wezterm":
        return [term, "start", "--", "sh", "-c", script]
    return [term, "--title", "Islet updates", "-e", "sh", "-c", script] if term == "alacritty" else \
        [term, "--title", "Islet updates", "sh", "-c", script]


class Updates:
    def __init__(self, on_change):
        self.on_change = on_change  # called from the worker thread
        self.repo, self.aur, self.flatpak = [], [], []
        self.checked = 0.0
        self.checking = False
        self.running = False
        self._lock = threading.Lock()
        try:  # last result, so the tile isn't empty right after a restart
            with open(CACHE) as f:
                c = json.load(f)
            self.repo, self.aur, self.flatpak, self.checked = c["repo"], c["aur"], c["flatpak"], c["checked"]
        except (OSError, ValueError, KeyError):
            pass

    @property
    def total(self):
        return len(self.repo) + len(self.aur) + len(self.flatpak)

    def summary(self):
        parts = [f"{n} {name}" for n, name in ((len(self.repo), "Arch"), (len(self.aur), "AUR"),
                                                (len(self.flatpak), "Flatpak")) if n]
        return " · ".join(parts) or "Up to date"

    def check(self):
        with self._lock:
            if self.checking:
                return
            self.checking = True
        self.on_change()
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        repo = _lines(["checkupdates"])
        if repo is None:  # another checkupdates had the sync database; try once more
            time.sleep(8)
            repo = _lines(["checkupdates"])
        aur = _lines(["yay", "-Qua"])
        fp = _lines(["flatpak", "remote-ls", "--updates", "--columns=application"])
        self.repo = repo or []
        self.aur = aur or []
        self.flatpak = [x for x in (fp or []) if x.lower() != "application id"]
        self.checked = time.time()
        self.checking = False
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w") as f:
                json.dump({"repo": self.repo, "aur": self.aur, "flatpak": self.flatpak, "checked": self.checked}, f)
        except OSError:
            pass
        self.on_change()

    def maybe_check(self, every_h):
        if not self.checking and not self.running and time.time() - self.checked > every_h * 3600:
            self.check()

    def run(self, conf, mode):
        """mode 0: yay -Syu + flatpak update in a terminal; mode 1: flatpak update -y, no terminal."""
        if self.running:
            return False
        if mode == 1:
            cmd = ["flatpak", "update", "-y", "--noninteractive"]
        else:
            skip = [shlex.quote(p) for p in re.split(r"[\s,]+", conf.get("upd_skip", "")) if p]
            ign = f" --ignore {','.join(skip)}" if skip else ""
            script = ('echo "Islet: updating Arch + AUR, then Flatpak"; '
                      + (f'echo "Skipping: {" ".join(skip)}"; ' if skip else "") + 'echo; '
                      + (f"yay -Syu{ign}; " if shutil.which("yay") else f"sudo pacman -Syu{ign}; ")
                      + "flatpak update; echo; printf 'Done. Press Enter to close. '; read _")
            cmd = terminal_cmd(conf, script)
            if not cmd:
                return False
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        self.running = True
        self.on_change()

        def wait():
            proc.wait()
            self.running = False
            self._check()

        threading.Thread(target=wait, daemon=True).start()
        return True
