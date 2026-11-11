"""Local stream proxy for the mini player.

YouTube only serves googlevideo streams to requests that carry a `range=` URL parameter (as
yt-dlp sends them, at most ~10 MB each); plain Range-header requests from mpv/ffmpeg get 403.
This serves each stream on 127.0.0.1 as an ordinary seekable file and fetches the bytes from
YouTube chunk by chunk with `&range=`.
"""
import json
import re
import shutil
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK = 4 * 1024 * 1024


class NeedsLogin(RuntimeError):
    """YouTube wants a signed-in user for this video (age limit, members only, bot check)."""


LOGIN_HINTS = ("sign in", "cookies", "not a bot", "age-restricted", "inappropriate", "members", "private video", "login required")


def find_browsers():
    """Browsers yt-dlp can read a YouTube login from: list of (label, --cookies-from-browser value)."""
    import glob
    import os
    home = os.path.expanduser("~")
    out = []
    firefoxish = [("LibreWolf", ["~/.librewolf", "~/.config/librewolf/librewolf",
                                 "~/.var/app/io.gitlab.librewolf-community/.librewolf"]),
                  ("Firefox", ["~/.mozilla/firefox", "~/.var/app/org.mozilla.firefox/.mozilla/firefox"]),
                  ("Zen", ["~/.zen", "~/.var/app/app.zen_browser.zen/.zen"]),
                  ("Floorp", ["~/.floorp"]), ("Waterfox", ["~/.waterfox"])]
    for label, roots in firefoxish:
        profiles = []
        for root in roots:
            profiles += glob.glob(os.path.join(os.path.expanduser(root), "*", "cookies.sqlite"))
        if profiles:
            newest = max(profiles, key=os.path.getmtime)  # the profile in use writes its cookies last
            out.append((label, "firefox:" + os.path.dirname(newest)))
    for label, name, d in (("Chrome", "chrome", ".config/google-chrome"), ("Chromium", "chromium", ".config/chromium"),
                           ("Brave", "brave", ".config/BraveSoftware/Brave-Browser"), ("Vivaldi", "vivaldi", ".config/vivaldi"),
                           ("Edge", "edge", ".config/microsoft-edge"), ("Opera", "opera", ".config/opera")):
        if os.path.isdir(os.path.join(home, d)):
            out.append((label, name))
    return out


def resolve(url, max_height=1080, timeout=60, cookies=None):
    """yt-dlp -j: list of (stream url, headers, kind) for the best video+audio up to max_height.
    cookies: a --cookies-from-browser value to use the browser's YouTube login."""
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp isn't installed")
    fmt = f"bv*[height<={max_height}][vcodec!*=av01]+ba/b[height<={max_height}]/b"
    cmd = ["yt-dlp", "-q", "--no-warnings", "--no-playlist", "-f", fmt, "-j", url]
    if cookies:
        cmd[1:1] = ["--cookies-from-browser", cookies]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not r.stdout.strip():
        msg = (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
        if any(h in msg.lower() for h in LOGIN_HINTS):
            raise NeedsLogin(msg)
        raise RuntimeError(msg)
    d = json.loads(r.stdout)
    fmts = d.get("requested_formats") or [d]
    out = []
    for f in fmts:
        kind = "video" if f.get("vcodec") not in (None, "none") else "audio"
        out.append((f["url"], f.get("http_headers") or d.get("http_headers") or {}, kind, f.get("filesize")))
    return out, d


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        st = self.server.streams.get(self.path.strip("/"))
        if not st:
            self.send_error(404)
            return
        size = st["size"]
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):  # suffix range: last N bytes
                start = max(0, size - int(m.group(2)))
        if start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", st["mime"])
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        pos = start
        try:
            while pos <= end:
                stop = min(end, pos + CHUNK - 1)
                req = urllib.request.Request(f"{st['url']}&range={pos}-{stop}", headers=st["headers"])
                with urllib.request.urlopen(req, timeout=20) as r:
                    while True:
                        buf = r.read(65536)
                        if not buf:
                            break
                        self.wfile.write(buf)
                        pos += len(buf)
                if pos <= stop:  # short read: try the rest again
                    continue
        except (BrokenPipeError, ConnectionResetError):
            pass  # mpv seeked or closed
        except OSError:
            pass


class Proxy:
    def __init__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.srv.daemon_threads = True
        self.srv.streams = {}
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def add(self, name, url, headers, size=None):
        if not size:
            m = re.search(r"[?&]clen=(\d+)", url)
            size = int(m.group(1)) if m else None
        if not size:
            req = urllib.request.Request(f"{url}&range=0-0", headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                cr = r.headers.get("Content-Range", "")
                size = int(cr.rsplit("/", 1)[1]) if "/" in cr else int(r.headers.get("Content-Length", 0))
        mime = re.search(r"[?&]mime=([^&]+)", url)
        mime = urllib.request.unquote(mime.group(1)) if mime else "application/octet-stream"
        self.srv.streams[name] = {"url": url, "headers": headers, "size": size, "mime": mime}
        return f"http://127.0.0.1:{self.port}/{name}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
