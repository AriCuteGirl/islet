"""Islet mini player: the browser's video in a small always-on-top overlay (libmpv in a GTK GLArea).

Plays the same URL (yt-dlp picks the stream) from the same second, with play/pause, ±10 s,
seek, volume, "back to browser" and close. Drag to move, drag the corner to resize.
"""
import ctypes
import locale
import os
import subprocess
import threading
import time
from ctypes import CFUNCTYPE, POINTER, Structure, c_char_p, c_double, c_int, c_int64, c_uint64, c_void_p

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

import ytproxy  # noqa: E402

# ------------------------------------------------------------------ libmpv (render API) via ctypes
_mpv = ctypes.CDLL("libmpv.so.2")
_egl = ctypes.CDLL("libEGL.so.1")
_egl.eglGetProcAddress.restype = c_void_p
_egl.eglGetProcAddress.argtypes = [c_char_p]

MPV_RENDER_PARAM_INVALID, MPV_RENDER_PARAM_API_TYPE = 0, 1
MPV_RENDER_PARAM_OPENGL_INIT_PARAMS, MPV_RENDER_PARAM_OPENGL_FBO, MPV_RENDER_PARAM_FLIP_Y = 2, 3, 4
GL_FRAMEBUFFER_BINDING = 0x8CA6


class RenderParam(Structure):
    _fields_ = [("type", c_int), ("data", c_void_p)]


GET_PROC = CFUNCTYPE(c_void_p, c_void_p, c_char_p)
UPDATE_CB = CFUNCTYPE(None, c_void_p)


class OpenGLInit(Structure):
    _fields_ = [("get_proc_address", GET_PROC), ("get_proc_address_ctx", c_void_p)]


class OpenGLFbo(Structure):
    _fields_ = [("fbo", c_int), ("w", c_int), ("h", c_int), ("internal_format", c_int)]


_mpv.mpv_create.restype = c_void_p
_mpv.mpv_initialize.argtypes = [c_void_p]
_mpv.mpv_set_option_string.argtypes = [c_void_p, c_char_p, c_char_p]
_mpv.mpv_set_property_string.argtypes = [c_void_p, c_char_p, c_char_p]
_mpv.mpv_get_property_string.restype = c_void_p
_mpv.mpv_get_property_string.argtypes = [c_void_p, c_char_p]
_mpv.mpv_free.argtypes = [c_void_p]
_mpv.mpv_command.argtypes = [c_void_p, POINTER(c_char_p)]
_mpv.mpv_terminate_destroy.argtypes = [c_void_p]
_mpv.mpv_render_context_create.argtypes = [POINTER(c_void_p), c_void_p, POINTER(RenderParam)]
_mpv.mpv_render_context_set_update_callback.argtypes = [c_void_p, UPDATE_CB, c_void_p]
_mpv.mpv_render_context_render.argtypes = [c_void_p, POINTER(RenderParam)]
_mpv.mpv_render_context_update.restype = c_uint64
_mpv.mpv_render_context_update.argtypes = [c_void_p]
_mpv.mpv_render_context_free.argtypes = [c_void_p]


@GET_PROC
def _get_proc(_ctx, name):
    return _egl.eglGetProcAddress(name)


_GLGETINTV = CFUNCTYPE(None, c_int, POINTER(c_int))


class Mpv:
    def __init__(self):
        locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv refuses to start with a comma decimal locale
        self.h = _mpv.mpv_create()
        if not self.h:
            raise RuntimeError("mpv_create failed")
        self.ctx = c_void_p()

    def opt(self, k, v):
        _mpv.mpv_set_option_string(self.h, k.encode(), str(v).encode())

    def init(self):
        if _mpv.mpv_initialize(self.h) < 0:
            raise RuntimeError("mpv_initialize failed")

    def cmd(self, *args):
        arr = (c_char_p * (len(args) + 1))(*[str(a).encode() for a in args], None)
        return _mpv.mpv_command(self.h, arr)

    def set(self, k, v):
        _mpv.mpv_set_property_string(self.h, k.encode(), str(v).encode())

    def get(self, k):
        p = _mpv.mpv_get_property_string(self.h, k.encode())
        if not p:
            return None
        v = ctypes.string_at(p).decode("utf-8", "replace")
        _mpv.mpv_free(p)
        return v

    def getf(self, k):
        try:
            return float(self.get(k))
        except (TypeError, ValueError):
            return None

    def create_gl(self, on_update):
        self._init = OpenGLInit(_get_proc, None)
        params = (RenderParam * 3)(
            RenderParam(MPV_RENDER_PARAM_API_TYPE, ctypes.cast(c_char_p(b"opengl"), c_void_p)),
            RenderParam(MPV_RENDER_PARAM_OPENGL_INIT_PARAMS, ctypes.cast(ctypes.pointer(self._init), c_void_p)),
            RenderParam(MPV_RENDER_PARAM_INVALID, None),
        )
        if _mpv.mpv_render_context_create(ctypes.byref(self.ctx), self.h, params) < 0:
            raise RuntimeError("mpv render context failed")
        self._cb = UPDATE_CB(lambda _d: on_update())
        _mpv.mpv_render_context_set_update_callback(self.ctx, self._cb, None)
        self._glgetintv = _GLGETINTV(_egl.eglGetProcAddress(b"glGetIntegerv"))

    def render(self, w, h):
        if not self.ctx:
            return
        fbo = c_int(0)
        self._glgetintv(GL_FRAMEBUFFER_BINDING, ctypes.byref(fbo))
        f = OpenGLFbo(fbo.value, w, h, 0)
        flip = c_int(1)
        params = (RenderParam * 3)(
            RenderParam(MPV_RENDER_PARAM_OPENGL_FBO, ctypes.cast(ctypes.pointer(f), c_void_p)),
            RenderParam(MPV_RENDER_PARAM_FLIP_Y, ctypes.cast(ctypes.pointer(flip), c_void_p)),
            RenderParam(MPV_RENDER_PARAM_INVALID, None),
        )
        _mpv.mpv_render_context_render(self.ctx, params)

    def free_gl(self):
        if self.ctx:
            _mpv.mpv_render_context_free(self.ctx)
            self.ctx = c_void_p()

    def destroy(self):
        self.free_gl()
        if self.h:
            _mpv.mpv_terminate_destroy(self.h)
            self.h = None


# ------------------------------------------------------------------ window
I = {"play": "\U000F040A", "pause": "\U000F03E4", "back": "\U000F045F", "fwd": "\U000F0211",
     "vol": "\U000F057E", "mute": "\U000F0581", "web": "\U000F059F", "close": "\U000F0156", "grip": "⤡"}

CSS = """
window.mini { background: transparent; }
.minibox { background: black; border-radius: 16px; border: 1px solid alpha(white, 0.10);
  box-shadow: 0 10px 30px alpha(black, 0.6); }
.minictl { background-image: linear-gradient(0deg, alpha(black, 0.85), alpha(black, 0.0)); padding: 18px 10px 8px 10px;
  border-radius: 0 0 16px 16px; }
.minitop { background-image: linear-gradient(180deg, alpha(black, 0.75), alpha(black, 0.0)); padding: 8px 10px 16px 12px;
  border-radius: 16px 16px 0 0; }
.minititle { color: white; font-weight: 800; font-size: 12px; }
button.mb { background: alpha(white, 0.10); border: none; box-shadow: none; color: white; border-radius: 999px;
  min-width: 30px; min-height: 30px; padding: 0; font-family: "Symbols Nerd Font"; font-size: 15px; }
button.mb:hover { background: alpha(white, 0.22); }
button.mb.big { min-width: 38px; min-height: 38px; font-size: 19px; background: alpha(white, 0.18); }
.minitime { color: alpha(white, 0.8); font-size: 11px; font-weight: 700; font-family: monospace; }
scale.miniseek trough { min-height: 4px; background: alpha(white, 0.2); border-radius: 2px; }
scale.miniseek highlight { background: #ff8fc7; border-radius: 2px; }
scale.miniseek slider { min-width: 12px; min-height: 12px; background: white; border: none; box-shadow: none; margin: -4px; }
.grip { color: alpha(white, 0.7); font-size: 16px; font-weight: 900; padding: 2px 4px; }
.loading { color: alpha(white, 0.7); font-weight: 700; }
.loginbox { background: alpha(black, 0.75); border-radius: 14px; padding: 14px 16px; }
.loginsub { color: alpha(white, 0.65); font-size: 11px; }
button.loginbtn { background: #ff8fc7; color: #101014; font-weight: 800; border: none; box-shadow: none;
  border-radius: 999px; padding: 3px 12px; }
button.loginlink { background: none; border: none; box-shadow: none; color: alpha(white, 0.7); font-size: 11px;
  text-decoration: underline; }
"""


def _fmt(t):
    if t is None:
        return "--:--"
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


class MiniPlayer(Gtk.Window):
    def __init__(self, app, url, start, title, monitor, conf, save_conf, cursor_pos, accent="#ff8fc7", browser=""):
        super().__init__(application=app)
        self.url, self.title_text = url, title
        self.browser = browser  # the playerctl name of the tab we came from
        self.conf, self.save_conf, self.cursor_pos = conf, save_conf, cursor_pos
        self.mp = Mpv()
        mc = conf.setdefault("mini", {})
        self.w = int(mc.get("w", 480))
        self.add_css_class("mini")
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS.replace("#ff8fc7", accent))
        Gtk.StyleContext.add_provider_for_display(self.get_display(), prov, 810)

        LS.init_for_window(self)
        LS.set_namespace(self, "islet-mini")
        LS.set_layer(self, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(self, -1)
        LS.set_anchor(self, LS.Edge.TOP, True)
        LS.set_anchor(self, LS.Edge.LEFT, True)
        if monitor:
            LS.set_monitor(self, monitor)
        geo = monitor.get_geometry() if monitor else None
        self.geo = geo
        self.pos = [int(mc.get("x", (geo.width - self.w - 24) if geo else 100)), int(mc.get("y", 70))]
        self._apply_pos()

        box = Gtk.Overlay()
        box.add_css_class("minibox")
        box.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_child(box)
        self.area = Gtk.GLArea()
        self.area.set_allowed_apis(Gdk_GL_API())
        self.area.set_auto_render(False)
        self.area.connect("realize", self._on_realize)
        self.area.connect("unrealize", self._on_unrealize)
        self.area.connect("render", self._on_render)
        self._size()
        box.set_child(self.area)

        self.loading = Gtk.Label(label="Loading video…")
        self.loading.add_css_class("loading")
        self.loading.set_wrap(True)
        self.loading.set_justify(Gtk.Justification.CENTER)
        self.loading.set_max_width_chars(40)
        box.add_overlay(self.loading)

        # shown when YouTube wants a signed-in user for this video
        self.login = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.login.add_css_class("loginbox")
        self.login.set_halign(Gtk.Align.CENTER)
        self.login.set_valign(Gtk.Align.CENTER)
        lt = Gtk.Label(label="YouTube wants you to sign in for this video")
        lt.add_css_class("minititle")
        lt.set_wrap(True)
        lt.set_justify(Gtk.Justification.CENTER)
        self.login.append(lt)
        ls = Gtk.Label(label="Islet can use the YouTube login from your browser.\nIt stays on this PC.")
        ls.add_css_class("loginsub")
        ls.set_justify(Gtk.Justification.CENTER)
        self.login.append(ls)
        self.login_btns = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                      column_spacing=6, row_spacing=6, halign=Gtk.Align.CENTER)
        self.login.append(self.login_btns)
        so = Gtk.Button(label="Sign in to YouTube in my browser")
        so.add_css_class("loginlink")
        so.set_can_focus(False)
        so.connect("clicked", lambda *_: subprocess.Popen(
            ["xdg-open", "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self.login.append(so)
        self.login.set_visible(False)
        box.add_overlay(self.login)

        # top bar: title + back to browser + close
        self.top = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=180)
        self.top.set_valign(Gtk.Align.START)
        tb = Gtk.Box(spacing=6)
        tb.add_css_class("minitop")
        t = Gtk.Label(label=title, xalign=0, hexpand=True)
        t.set_ellipsize(3)
        t.add_css_class("minititle")
        tb.append(t)
        tb.append(self._btn(I["web"], self.back_to_browser, "Back to the browser at this point"))
        tb.append(self._btn(I["close"], self.close_player, "Close"))
        self.top.set_child(tb)
        box.add_overlay(self.top)

        # bottom bar: controls + seek
        self.ctl = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, transition_duration=180)
        self.ctl.set_valign(Gtk.Align.END)
        cb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cb.add_css_class("minictl")
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_draw_value(False)
        self.seek.add_css_class("miniseek")
        self.seek.connect("change-value", self._on_seek)
        cb.append(self.seek)
        row = Gtk.Box(spacing=8)
        row.append(self._btn(I["back"], lambda: self.mp.cmd("seek", "-10"), "Back 10 s"))
        self.pp = self._btn(I["pause"], self.toggle, "Play / pause", big=True)
        row.append(self.pp)
        row.append(self._btn(I["fwd"], lambda: self.mp.cmd("seek", "10"), "Forward 10 s"))
        self.time = Gtk.Label(label="--:-- / --:--")
        self.time.add_css_class("minitime")
        row.append(self.time)
        row.append(Gtk.Box(hexpand=True))
        self.vol = self._btn(I["vol"], self.toggle_mute, "Mute (scroll to change volume)")
        sc = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        sc.connect("scroll", self._on_vol_scroll)
        self.vol.add_controller(sc)
        row.append(self.vol)
        grip = Gtk.Label(label=I["grip"])
        grip.add_css_class("grip")
        grip.set_cursor_from_name("se-resize")
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._resize_begin)
        g.connect("drag-update", self._resize_update)
        g.connect("drag-end", lambda *_: self._remember())
        grip.add_controller(g)
        row.append(grip)
        cb.append(row)
        self.ctl.set_child(cb)
        box.add_overlay(self.ctl)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._show_ctl(True))
        motion.connect("leave", lambda *_: self._show_ctl(False))
        box.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.area.add_controller(drag)
        click = Gtk.GestureClick()
        click.connect("released", self._area_click)
        self.area.add_controller(click)

        self._dragging = self._dragged = False
        self.mp.opt("vo", "libmpv")
        self.mp.opt("hwdec", "auto-safe")
        self.mp.opt("ytdl", "no")  # we resolve with yt-dlp ourselves and stream through ytproxy
        self.mp.opt("log-file", os.path.expanduser("~/.cache/islet/mpv.log"))
        self.mp.opt("cache", "yes")
        self.mp.opt("demuxer-max-bytes", "150MiB")
        self.mp.opt("keep-open", "yes")
        self.mp.opt("volume", mc.get("volume", 80))
        self.mp.init()
        self.proxy = None
        self.start = start
        threading.Thread(target=self._resolve, daemon=True).start()
        self.add_tick_callback(self._tick)
        GLib.timeout_add(250, self._poll)
        self.present()

    def _resolve(self, cookies=None):
        """yt-dlp picks the streams (takes a few seconds); then load them through the local proxy."""
        if cookies is None and self.conf.get("yt_login") and self.conf.get("yt_cookies"):
            cookies = self.conf["yt_cookies"]
        try:
            streams, _info = ytproxy.resolve(self.url, cookies=cookies)
            urls = {}
            for u, headers, kind, size in streams:
                if "googlevideo.com" in u:
                    if self.proxy is None:
                        self.proxy = ytproxy.Proxy()
                    urls[kind] = self.proxy.add(kind, u, headers, size)
                else:
                    urls[kind] = u
            GLib.idle_add(self._load, urls)
        except ytproxy.NeedsLogin as e:
            GLib.idle_add(self._ask_login, str(e), bool(cookies))
        except Exception as e:
            GLib.idle_add(self.loading.set_text, f"Couldn't load: {str(e)[:80]}")

    def _ask_login(self, msg, tried):
        self.loading.set_visible(False)
        while (c := self.login_btns.get_first_child()) is not None:
            self.login_btns.remove(c)
        browsers = ytproxy.find_browsers()
        for label, spec in browsers[:4]:
            b = Gtk.Button(label=f"Use my {label} login")
            b.add_css_class("loginbtn")
            b.set_can_focus(False)
            b.connect("clicked", lambda _b, sp=spec: self._use_login(sp))
            self.login_btns.append(b)
        if tried:
            self.login.get_first_child().set_text("Still no luck: sign in to YouTube in your browser first")
        if not browsers:
            self.login.get_first_child().set_text("YouTube wants a sign-in, and no browser login was found")
        self.login.set_visible(True)
        return False

    def _use_login(self, spec):
        """Remember the choice (Settings → Videos shows it) and try again with that login."""
        self.conf["yt_login"], self.conf["yt_cookies"] = True, spec
        self.save_conf(self.conf)
        self.login.set_visible(False)
        self.loading.set_text("Loading video with your login…")
        self.loading.set_visible(True)
        threading.Thread(target=self._resolve, args=(spec,), daemon=True).start()

    def _load(self, urls):
        if not self.mp.h:
            return False
        if self.start and self.start > 1:
            self.mp.set("start", f"{self.start:.1f}")
        if "audio" in urls and "video" in urls:
            self.mp.cmd("change-list", "audio-files", "append", urls["audio"])  # one item: URLs contain ':' 
        self.mp.cmd("loadfile", urls.get("video") or urls.get("audio"))
        self._t0 = time.time()
        return False

    # -------------------------------------------------------------- gl
    def _on_realize(self, area):
        area.make_current()
        if area.get_error():
            return
        self.mp.create_gl(lambda: GLib.idle_add(self._queue))

    def _queue(self):
        if self.mp.ctx:
            self.area.queue_render()
        return False

    def _on_render(self, area, _ctx):
        s = area.get_scale_factor()
        self.mp.render(area.get_width() * s, area.get_height() * s)
        return True

    def _on_unrealize(self, area):
        area.make_current()
        self.mp.free_gl()

    # -------------------------------------------------------------- controls
    def _btn(self, icon, cb, tip, big=False):
        b = Gtk.Button(label=icon)
        b.add_css_class("mb")
        if big:
            b.add_css_class("big")
        b.set_can_focus(False)
        b.set_tooltip_text(tip)
        b.connect("clicked", lambda *_: cb())
        return b

    def _show_ctl(self, v):
        self.top.set_reveal_child(v)
        self.ctl.set_reveal_child(v)

    def toggle(self):
        self.mp.cmd("cycle", "pause")

    def toggle_mute(self):
        self.mp.cmd("cycle", "mute")

    def _on_vol_scroll(self, _c, _dx, dy):
        self.mp.cmd("add", "volume", "-5" if dy > 0 else "5")
        return True

    def _on_seek(self, _s, _scroll, value):
        self.mp.cmd("seek", f"{value:.1f}", "absolute")
        return False

    def _area_click(self, _g, n, _x, _y):
        if self._dragged:
            return
        if n == 2:
            self.back_to_browser()
        else:
            self.toggle()

    def _poll(self):
        if not self.mp.h:
            return False
        pos, dur = self.mp.getf("time-pos"), self.mp.getf("duration")
        paused = self.mp.get("pause") == "yes"
        if pos is not None:
            self.loading.set_visible(False)
        if dur:
            self.seek.set_range(0, dur)
            self.seek.set_value(pos or 0)
        self.time.set_text(f"{_fmt(pos)} / {_fmt(dur)}")
        self.pp.set_label(I["play"] if paused else I["pause"])
        self.vol.set_label(I["mute"] if self.mp.get("mute") == "yes" else I["vol"])
        if getattr(self, "_t0", None) and self.mp.get("idle-active") == "yes" and pos is None \
                and time.time() - self._t0 > 25:
            self.loading.set_text("Couldn't play this video")
        return True

    # -------------------------------------------------------------- move / resize
    def _apply_pos(self):
        LS.set_margin(self, LS.Edge.LEFT, max(0, self.pos[0]))
        LS.set_margin(self, LS.Edge.TOP, max(0, self.pos[1]))

    def _size(self):
        self.w = max(280, min(1400, self.w))
        self.area.set_size_request(self.w, self.w * 9 // 16)

    def _drag_begin(self, _g, x, y):
        self._dragging, self._dragged, self._grab = True, False, (x, y)

    def _drag_update(self, _g, ox, oy):
        if abs(ox) + abs(oy) > 5:
            self._dragged = True

    def _drag_end(self, *_):
        self._dragging = False
        if self._dragged:
            self._remember()
            GLib.timeout_add(80, lambda: setattr(self, "_dragged", False) or False)

    def _resize_begin(self, _g, _x, _y):
        self._w0 = self.w

    def _resize_update(self, _g, ox, oy):
        self.w = int(self._w0 + max(ox, oy * 16 / 9))
        self._size()

    def _tick(self, *_):
        if self._dragging and self._dragged and self.geo:
            c = self.cursor_pos()
            if c:
                g = self.geo
                x = int(min(max(0, c[0] - g.x - self._grab[0]), g.width - self.w))
                y = int(min(max(0, c[1] - g.y - self._grab[1]), g.height - 60))
                if [x, y] != self.pos:
                    self.pos = [x, y]
                    self._apply_pos()
        return True

    def _remember(self):
        mc = self.conf.setdefault("mini", {})
        mc.update(x=self.pos[0], y=self.pos[1], w=self.w)
        vol = self.mp.getf("volume") if self.mp.h else None
        if vol is not None:
            mc["volume"] = int(vol)
        self.save_conf(self.conf)

    # -------------------------------------------------------------- leave
    def back_to_browser(self):
        pos = self.mp.getf("time-pos")
        self.close_player()
        if pos is not None:
            subprocess.run(self._pc("position", f"{pos:.1f}"), capture_output=True, timeout=3)
        subprocess.Popen(self._pc("play"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _pc(self, *args):
        return ["playerctl", "-p", self.browser, *args] if self.browser else ["playerctl", *args]

    def close_player(self):
        self._remember()
        self.set_visible(False)
        GLib.idle_add(self._teardown)

    def _teardown(self):
        self.mp.destroy()
        if self.proxy:
            self.proxy.close()
        self.destroy()
        return False


def Gdk_GL_API():
    from gi.repository import Gdk
    return Gdk.GLAPI.GL | Gdk.GLAPI.GLES
