#!/usr/bin/python3
"""Islet: a dynamic island for Claude Code and Codex on Linux (Wayland, layer-shell).

  islet              run the island
  islet hook SRC     hook entry point (SRC = claude | codex), reads the event on stdin
  islet allow|deny|terminal   answer the waiting permission (bind these to keys)
  islet run NAME     press one of your script buttons
  islet welcome      show the login hello again
  islet mini         pop the browser's video out into the mini player
  islet toggle       open/close the panel   (islet open home|settings|updates)
  islet pet pup|kitty  switch between Pip and Mochi
  islet monitor 1|2|next|NAME   move the island to a monitor (1 = leftmost, or e.g. DP-2)
  islet center       move the island back to the top middle
  islet push --app APP [--id ID] --title T [--detail D] [--color #hex] [--mood M] [--ttl SECS]
                     show a live activity from any script; islet clear --app APP [--id ID] removes it
  islet toast --app APP --title T [--body B] [--color #hex]   a quick notification in the island
  islet install      add hooks to ~/.claude/settings.json and ~/.codex/hooks.json
  islet uninstall    remove them again
"""
import json
import os
import socket
import sys

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "islet.sock")
HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.path.expanduser("~/.local/share/islet")
CONF = os.path.expanduser("~/.config/islet/config.json")
LOG = os.path.expanduser("~/.cache/islet/events.jsonl")
HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PermissionRequest", "Notification", "Stop", "SessionEnd"]
MATCHER_EVENTS = {"PreToolUse", "PostToolUse", "PermissionRequest"}
CODEX_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                "PermissionRequest", "Stop", "SessionEnd"]
PERM_TIMEOUT = 600


# --------------------------------------------------------------------------- hook (stdlib only, fast)

def run_hook(src):
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCK)
        s.sendall((json.dumps({"src": src, "ev": ev}) + "\n").encode())
    except OSError:
        return 0  # island not running: behave as if there were no hook
    if ev.get("hook_event_name") != "PermissionRequest":
        s.close()
        return 0
    s.settimeout(None)
    buf = b""
    try:
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except OSError:
        return 0
    try:
        decision = json.loads(buf.decode().strip() or "{}").get("decision")
    except ValueError:
        return 0
    if decision == "allow":
        d = {"behavior": "allow"}
    elif decision == "deny":
        d = {"behavior": "deny", "message": "Denied from Islet."}
    else:
        return 0  # "ask": fall back to the normal terminal prompt
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": d}}))
    return 0


def send_cmd(cmd, **kw):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCK)
        s.sendall((json.dumps(dict(cmd=cmd, **kw)) + "\n").encode())
        s.close()
        return 0
    except OSError:
        print("islet is not running", file=sys.stderr)
        return 1


# --------------------------------------------------------------------------- install / uninstall

def _is_ours(h):
    c = str(h.get("command", ""))
    return "islet.py hook " in c or "islet hook " in c


def _strip(hooks):
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            g = dict(g)
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h)]
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            del hooks[ev]
    return hooks


def _merge(path, src, events):
    data = {}
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        with open(path + ".islet-bak", "w") as f:
            json.dump(data, f, indent=2)
    hooks = _strip(data.get("hooks", {}))
    cmd = f"/usr/bin/python3 {os.path.realpath(__file__)} hook {src}"
    for ev in events:
        h = {"type": "command", "command": cmd, "timeout": PERM_TIMEOUT if ev == "PermissionRequest" else 5}
        g = {"hooks": [h]}
        if ev in MATCHER_EVENTS:
            g["matcher"] = "*"
        hooks.setdefault(ev, []).append(g)
    data["hooks"] = hooks
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"hooks added: {path}")


def _unmerge(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        data = json.load(f)
    data["hooks"] = _strip(data.get("hooks", {}))
    if not data["hooks"]:
        del data["hooks"]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"hooks removed: {path}")


def install():
    _merge(os.path.expanduser("~/.claude/settings.json"), "claude", HOOK_EVENTS)
    _merge(os.path.expanduser("~/.codex/hooks.json"), "codex", CODEX_EVENTS)
    b = os.path.expanduser("~/.local/bin/islet")
    os.makedirs(os.path.dirname(b), exist_ok=True)
    if os.path.islink(b) or not os.path.exists(b):
        if os.path.islink(b):
            os.unlink(b)
        os.symlink(os.path.realpath(__file__), b)
        print(f"linked {b}")
    print("start it with: islet &   (Hyprland autostart: exec-once = islet)")


def uninstall():
    _unmerge(os.path.expanduser("~/.claude/settings.json"))
    _unmerge(os.path.expanduser("~/.codex/hooks.json"))


# --------------------------------------------------------------------------- island

def ensure_preload():
    lib = "/usr/lib/libgtk4-layer-shell.so"
    pre = os.environ.get("LD_PRELOAD", "")
    if "gtk4-layer-shell" not in pre and os.path.exists(lib):
        os.environ["LD_PRELOAD"] = (lib + " " + pre).strip()
        os.execv(sys.executable, [sys.executable] + sys.argv)


def run_island():
    """Watchdog: run the island in a child process and start it again if it crashes."""
    if os.environ.get("ISLET_CHILD"):
        return _island_child()
    import subprocess
    import time
    env = dict(os.environ, ISLET_CHILD="1")
    crashes = []
    while True:
        code = subprocess.call([sys.executable, os.path.realpath(__file__)] + sys.argv[1:], env=env)
        if code in (0, 2):  # quit normally / already running
            return 0 if code == 0 else 0
        now = time.time()
        crashes = [t for t in crashes if now - t < 60] + [now]
        if len(crashes) > 5:
            print("islet: crashed 5 times in a minute, giving up", file=sys.stderr)
            return 1
        time.sleep(1)


def _island_child():
    import faulthandler
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    crash = open(os.path.join(os.path.dirname(LOG), "crash.log"), "a")
    crash.write(f"\n--- islet started {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}\n")
    crash.flush()
    faulthandler.enable(file=crash, all_threads=True)  # Python stack of every thread on a segfault
    ensure_preload()
    sys.path.insert(0, HERE)
    import island
    # The layer-shell library is loaded now. Don't hand LD_PRELOAD to everything Islet starts
    # (terminals, yay, git, mpv, scripts): it broke git inside yay's builds.
    pre = [p for p in os.environ.get("LD_PRELOAD", "").split() if "gtk4-layer-shell" not in p]
    if pre:
        os.environ["LD_PRELOAD"] = " ".join(pre)
    else:
        os.environ.pop("LD_PRELOAD", None)
    return island.main()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "hook":
        sys.exit(run_hook(a[1] if len(a) > 1 else "claude"))
    if a and a[0] in ("allow", "deny", "terminal"):
        sys.exit(send_cmd("answer", decision={"terminal": "ask"}.get(a[0], a[0])))
    if a and a[0] in ("push", "clear", "toast"):
        kw, it = {}, iter(a[1:])
        for flag in it:
            if flag.startswith("--"):
                kw[flag[2:]] = next(it, "")
        sys.exit(send_cmd(a[0], **kw))
    if a and a[0] == "pet" and len(a) > 1:
        sys.exit(send_cmd("pet", pet=a[1]))
    if a and a[0] == "open":
        sys.exit(send_cmd("open", page=a[1] if len(a) > 1 else "home"))
    if a and a[0] == "run" and len(a) > 1:
        sys.exit(send_cmd("run", name=" ".join(a[1:])))
    if a and a[0] == "simdrag" and len(a) >= 5:
        sys.exit(send_cmd("simdrag", x1=a[1], y1=a[2], x2=a[3], y2=a[4], secs=a[5] if len(a) > 5 else "1"))
    if a and a[0] == "monitor" and len(a) > 1:
        sys.exit(send_cmd("monitor", name=a[1]))
    if a and a[0] == "welcome":
        sys.exit(send_cmd("welcome"))
    if a and a[0] == "mini":
        sys.exit(send_cmd("mini"))
    if a and a[0] == "check-updates":
        sys.exit(send_cmd("check-updates"))
    if a and a[0] in ("toggle", "center"):
        sys.exit(send_cmd(a[0]))
    if a and a[0] == "toggle":
        sys.exit(send_cmd("toggle"))
    if a and a[0] == "install":
        install()
    elif a and a[0] == "uninstall":
        uninstall()
    elif a and a[0] in ("-h", "--help", "help"):
        print(__doc__)
    else:
        sys.exit(run_island())
