"""Islet island window: GTK4 + gtk4-layer-shell. Started through islet.py (sets LD_PRELOAD)."""
import collections
import datetime
import json
import math
import os
import random
import socket
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_foreign("cairo")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

import actions  # noqa: E402
import dashboard  # noqa: E402
import highlight  # noqa: E402
import pets as pip  # noqa: E402
import sources  # noqa: E402
import updates as upd  # noqa: E402
from islet import DATA, LOG, SOCK  # noqa: E402
import model  # noqa: E402
from model import (COLORS, DEFAULT_CONF, MOOD_FOR, NO_BLOCK_TOOLS, Pending, Session, _first_line,  # noqa: E402
                   describe, ensure_assets, hex_rgb, last_assistant_text, load_conf, save_conf)

PILL_CSS = """
window.islet { background: transparent; }
window.islet-catcher { background: rgba(0, 0, 0, 0.01); }  /* fully transparent gets no buffer, so no clicks */
.pill {
  background: #050506; color: #f2f2f2; border-radius: 20px; padding: 4px 6px 4px 12px;
  border: 1px solid alpha(white, 0.07); min-height: 32px;
  box-shadow: 0 0 14px 0 alpha(@glow, 0.35), 0 4px 14px alpha(black, 0.5);
  transition: box-shadow 400ms ease;
}
.pill.idle { box-shadow: 0 4px 14px alpha(black, 0.5); }
.pill.question { animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse {
  0%   { box-shadow: 0 0 6px 0 alpha(@glow, 0.25), 0 4px 14px alpha(black, 0.5); }
  50%  { box-shadow: 0 0 22px 2px alpha(@glow, 0.6), 0 4px 14px alpha(black, 0.5); }
  100% { box-shadow: 0 0 6px 0 alpha(@glow, 0.25), 0 4px 14px alpha(black, 0.5); }
}
.title { font-weight: 700; font-size: 13px; }
.badge { background: alpha(white, 0.12); border-radius: 9px; padding: 0 6px; font-size: 11px; font-weight: 700; }
.toastsub { font-size: 12px; color: alpha(white, 0.72); }
.pill.toast { padding-top: 7px; padding-bottom: 7px; border-color: alpha(@glow, 0.45);
  animation: pop 700ms ease-out; }
@keyframes pop {
  0%   { box-shadow: 0 0 0 0 alpha(@glow, 0.9), 0 4px 14px alpha(black, 0.5); }
  100% { box-shadow: 0 0 18px 1px alpha(@glow, 0.35), 0 4px 14px alpha(black, 0.5); }
}
.pillbar trough { min-height: 3px; background: alpha(white, 0.12); border-radius: 2px; }
.pillbar progress { min-height: 3px; background: @glow; border-radius: 2px; }
button.allow, button.deny, button.term {
  border-radius: 999px; padding: 2px 14px; min-height: 24px; font-weight: 700; font-size: 12px;
  border: none; box-shadow: none; background-image: none;
}
button.allow { background: #cdf3a9; color: #10220a; }
button.allow:hover { background: #def9c4; }
button.deny { background: #3b1c1c; color: #ffb2a8; }
button.deny:hover { background: #4f2424; }
button.term { background: alpha(white, 0.08); color: alpha(white, 0.75); padding: 2px 9px; }
button.term:hover { background: alpha(white, 0.16); }
"""


DEBUG = os.environ.get("ISLET_DEBUG")


def dbg(*a):
    if DEBUG:
        with open(os.path.expanduser("~/.cache/islet/input.log"), "a") as f:
            f.write(f"{time.time():.3f} " + " ".join(map(str, a)) + "\n")


def _die_with_parent():
    """For long-running helpers (playerctl --follow): exit when Islet exits instead of lingering."""
    import ctypes
    import signal
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def hypr_cursor():
    """Global cursor position from Hyprland's socket (fast, no fork), or None elsewhere."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), "hypr", sig, ".socket.sock")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.05)
        s.connect(path)
        s.sendall(b"j/cursorpos")
        buf = b""
        while True:
            chunk = s.recv(256)
            if not chunk:
                break
            buf += chunk
        s.close()
        d = json.loads(buf)
        return int(d["x"]), int(d["y"])
    except (OSError, ValueError, KeyError):
        return None


FAKE_CURSOR = None  # tests: a function returning (x, y) instead of Hyprland's cursor


def cursor_pos():
    return FAKE_CURSOR() if FAKE_CURSOR else hypr_cursor()


def _rgb_css(rgb):
    r, g, b = rgb
    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"


class Pet(Gtk.DrawingArea):
    def __init__(self, island, size):
        super().__init__()
        self.island = island
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)
        self.glow = size > 40

    def _draw(self, _a, cr, w, h):
        isl = self.island
        pip.draw(cr, w, h, isl.mood(), isl.t, isl.blink, isl.accent(), glow=0.7 if self.glow else 0.0,
                 species=isl.conf["pet"])


class Dot(Gtk.DrawingArea):
    def __init__(self, island):
        super().__init__()
        self.island = island
        self.set_content_width(10)
        self.set_content_height(10)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def _draw(self, _a, cr, w, h):
        r, g, b = self.island.accent()
        a = 1.0
        if self.island.state() in ("working", "question", "activity"):
            a = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.island.t * 4))
        cr.arc(w / 2, h / 2, 4, 0, 2 * math.pi)
        cr.set_source_rgba(r, g, b, a)
        cr.fill()


class Island(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.conf = load_conf()
        model.PROJECT_NAMES.update(self.conf.get("names") or {})
        self.sessions = {}
        self.pending = []
        self.activities = {}
        self.inbox = collections.deque(maxlen=40)
        self._toast_n = 0
        self.music = {}
        self.game = None  # {"key", "name", "since"}
        self.timer_end = None
        self.timer_left = None
        self.updates = upd.Updates(lambda: GLib.idle_add(self._updates_changed))
        self.runner = actions.Runner(lambda app_, aid, act: GLib.idle_add(self.post_activity, app_, aid, act),
                                     lambda k, t, b: GLib.idle_add(self.alert, k, t, b))
        self._upd_seen = None
        self.t = 0.0
        self.blink = 0.0
        self._next_blink = time.time() + 3
        self._slow_at = 0.0
        self.hover = False
        self.panel_open = False
        self.override_mood = None
        self.override_until = 0.0
        self.pokes = collections.deque(maxlen=6)
        self._region = None
        self._last_sig = None
        self._dragging = False
        self._dragged = False

        self.add_css_class("islet")
        self.set_decorated(False)
        self.set_resizable(False)
        LS.init_for_window(self)
        LS.set_namespace(self, "islet")
        LS.set_layer(self, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(self, -1)  # place relative to the whole screen, ignoring bars
        mon = self._monitor_by_name(self.conf.get("monitor"))
        if mon:
            LS.set_monitor(self, mon)
        self._place()

        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css, 800)
        self._css_sig = None
        self._apply_css()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("start", "end", "bottom"):
            getattr(root, f"set_margin_{side}")(14 if side != "bottom" else 22)
        root.set_margin_top(2)
        root.set_halign(Gtk.Align.START)
        self.set_child(root)

        # ---- pill
        self.pill = Gtk.Box(spacing=8)
        self.pill.add_css_class("pill")
        self.pill.set_halign(Gtk.Align.START)
        root.append(self.pill)
        self.dot = Dot(self)
        self.pill.append(self.dot)
        self.text_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT, transition_duration=260)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        tb.set_valign(Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("title")
        self.title.set_ellipsize(3)
        self.title.set_max_width_chars(46)
        tb.append(self.title)
        self.sub = Gtk.Label(xalign=0)
        self.sub.add_css_class("toastsub")
        self.sub.set_ellipsize(3)
        self.sub.set_max_width_chars(52)
        self.sub.set_visible(False)
        tb.append(self.sub)
        self.pillbar = Gtk.ProgressBar()
        self.pillbar.add_css_class("pillbar")
        self.pillbar.set_pulse_step(0.06)
        self.pillbar.set_visible(False)
        tb.append(self.pillbar)
        self.text_rev.set_child(tb)
        self.pill.append(self.text_rev)

        self.perm_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=220)
        pb = Gtk.Box(spacing=6)
        pb.set_valign(Gtk.Align.CENTER)
        for label, css, dec in (("Allow", "allow", "allow"), ("Deny", "deny", "deny"), ("⌨", "term", "ask")):
            b = Gtk.Button(label=label)
            b.add_css_class(css)
            b.set_can_focus(False)
            b.connect("clicked", lambda _b, d=dec: self.answer(d))
            if dec == "ask":
                b.set_tooltip_text("Answer in the terminal")
            pb.append(b)
        self.perm_rev.set_child(pb)
        self.pill.append(self.perm_rev)

        self.badge = Gtk.Label()
        self.badge.add_css_class("badge")
        self.badge.set_valign(Gtk.Align.CENTER)
        self.pill.append(self.badge)
        self.pet = Pet(self, 30)
        self.pet.set_valign(Gtk.Align.CENTER)
        self.pill.append(self.pet)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.pill.add_controller(drag)
        click = Gtk.GestureClick()
        click.connect("released", self._pill_click)
        click.connect("pressed", lambda g, n, x, y: dbg("pressed", n, x, y))
        self.pill.add_controller(click)
        pet_click = Gtk.GestureClick()
        pet_click.connect("pressed", self._poke)
        self.pet.add_controller(pet_click)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_hover(True))
        motion.connect("leave", lambda *_: self._set_hover(False))
        self.pill.add_controller(motion)

        # ---- dashboard
        self.panel_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=240)
        self.dash = dashboard.Dashboard(self, lambda size: Pet(self, size))
        self.panel_rev.set_child(self.dash)
        self.panel_rev.set_visible(False)
        self.panel_rev.set_halign(Gtk.Align.START)
        # once the panel has slid away, drop it so the window is only as wide as the pill
        self.panel_rev.connect("notify::child-revealed",
                               lambda r, _p: r.set_visible(False) if not self.panel_open and not r.get_child_revealed() else None)
        root.append(self.panel_rev)

        self.add_tick_callback(self._tick)
        self.connect("notify::is-active", self._active_changed)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _kc, _st: (self.close_panel(), True)[1]
                     if kv == Gdk.KEY_Escape and self.panel_open else False)
        self.add_controller(keys)
        GLib.timeout_add_seconds(30, self._sweep)
        GLib.timeout_add_seconds(2, self._ensure_shown)
        GLib.timeout_add(1800, self.welcome)
        threading.Thread(target=self._music_loop, daemon=True).start()
        GLib.timeout_add_seconds(20, self._first_update_check)
        self.refresh()

    # ================================================================== state
    def app_on(self, app):
        return self.conf.setdefault("apps", {}).get(app, True)

    def live_acts(self):
        now = time.time()
        acts = [a for a in self.activities.values() if self.app_on(a["app"])]
        acts = [a for a in acts if not (a.get("flash") or a.get("ttl")) or a.get("until", 0) > now]
        return sorted(acts, key=lambda a: (not a.get("toast"), bool(a.get("flash")), a["app"] == "timer", -a["added"]))

    def top_act(self):
        if self.pending:
            return None
        acts = self.live_acts()
        if not acts:
            return None
        if acts[0].get("toast"):
            return acts[0]
        p = self.primary()
        if p and p.state in ("question", "working") and (acts[0].get("flash") or acts[0]["app"] == "timer"):
            return None
        return acts[0]

    def primary(self):
        if self.pending:
            return self.pending[0].sess
        live = sorted((s for s in self.sessions.values() if self.app_on(s.src)), key=lambda s: s.updated, reverse=True)
        for s in live:
            if s.state in ("question", "working"):
                return s
        return live[0] if live else None

    def state(self):
        if self.pending:
            return "question"
        if self.top_act():
            return "activity"
        p = self.primary()
        return p.state if p else "idle"

    def accent(self):
        st = self.state()
        if st == "activity":
            return hex_rgb(self.top_act().get("color"))
        if st == "idle":
            return hex_rgb(self.conf.get("accent"))
        return COLORS[st]

    def mood(self):
        now = time.time()
        if self.override_mood and now < self.override_until:
            return self.override_mood
        st = self.state()
        if st == "activity":
            return self.top_act().get("mood") or "focus"
        p = self.primary()
        if self.app_on("nowplaying") and (st == "idle" or (st == "done" and p and now - p.done_at > 8)):
            np = self.now_playing()
            if np:
                return np[1]  # awake while you game or watch something
        if st == "done" and p and now - p.done_at > 8:
            return "wink" if (int(now / 6) % 5 == 0) else "happy" if now - p.done_at < 60 else "sleepy"
        return MOOD_FOR[st]

    def _apply_css(self):
        sig = (self.accent(), self.conf.get("accent"))
        if sig == self._css_sig:
            return
        self._css_sig = sig
        head = (f"@define-color glow {_rgb_css(self.accent())};\n"
                f"@define-color accent {_rgb_css(hex_rgb(self.conf.get('accent')))};\n")
        self.css.load_from_string(head + PILL_CSS + dashboard.CSS)

    # ================================================================== UI
    def refresh(self):
        self._apply_css()
        st = self.state()
        for c in ("idle", "working", "question", "done", "activity"):
            (self.pill.add_css_class if c == st else self.pill.remove_css_class)(c)
        p = self.primary()
        act = self.top_act()
        show_text = False
        bar = None
        if self.pending:
            self.title.set_text(f"{self.pet_name()} asks: {self.pending[0].label}?")
            show_text = True
        elif act and act.get("toast"):
            self.title.set_text(act["title"])
            show_text = True
        elif act:
            self.title.set_text(self._act_text(act))
            show_text = True
            if act.get("progress") is not None:
                bar = act["progress"]
            elif act.get("total") and act.get("until"):
                bar = max(0.0, min(1.0, (act["until"] - time.time()) / act["total"]))
            elif act.get("pulse"):
                bar = "pulse"
        elif p:
            if p.state == "done":
                first = _first_line(p.answer, 60) if p.answer else ""
                self.title.set_text(f"{self.pet_name()} is done ✓" + (f" — {first}" if first else ""))
            else:
                diff = ""
                c = p.code
                if p.state == "working" and c and c["kind"] != "bash" and time.time() - c["t0"] < 30:
                    diff = f"  +{len(c['added'])} −{len(c['removed'])}"
                self.title.set_text(f"{self.pet_name()} {model.pet_phrase(p.text)}{diff}")
            recent = p.state == "done" and time.time() - p.done_at < self.conf["done_linger"]
            show_text = p.state in ("working", "question") or recent
            np = None if show_text or not self.app_on("nowplaying") else self.now_playing()
            if np:
                self.title.set_text(np[0])
                show_text = True
        else:
            np = self.now_playing() if self.app_on("nowplaying") else None
            if np:
                self.title.set_text(np[0])
                show_text = True
        is_toast = bool(act and act.get("toast") and not self.pending)
        self.sub.set_visible(is_toast and bool(act.get("detail")))
        if is_toast:
            self.sub.set_text(act.get("detail", ""))
        (self.pill.add_css_class if is_toast else self.pill.remove_css_class)("toast")
        self.pillbar.set_visible(bar is not None)
        if isinstance(bar, float):
            self.pillbar.set_fraction(bar)
        self._pill_pulse = bar == "pulse"
        self.text_rev.set_reveal_child(show_text)
        self.perm_rev.set_reveal_child(bool(self.pending))
        n_live = len([s for s in self.sessions.values() if self.app_on(s.src)]) + len(self.live_acts())
        extra = len(self.pending) - 1 if self.pending else n_live - 1
        self.badge.set_text(f"+{extra}")
        self.badge.set_visible(extra > 0)
        if self.panel_open:
            self.panel_rev.set_visible(True)
        self.panel_rev.set_reveal_child(self.panel_open)
        if self.panel_open:
            self.dash.refresh()

    def _act_text(self, a):
        t = a["title"] + (f" · {a['detail']}" if a.get("detail") else "")
        if a.get("until") and not a.get("flash") and not a.get("ttl"):
            left = max(0.0, a["until"] - time.time())
            t += f" · {int(left // 60)}:{int(left % 60):02d}" if left >= 60 else f" · {left:.1f}s"
        return t

    def close_panel(self):
        self.panel_open = False
        self._was_active = False
        LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
        if getattr(self, "catcher", None) is not None:
            self.catcher.set_visible(False)
        self.refresh()

    def open_panel(self, page="home"):
        self.panel_open = True
        self._was_active = False
        LS.set_keyboard_mode(self, LS.KeyboardMode.ON_DEMAND)
        self.dash.show(page)
        self._show_catcher()
        self.refresh()

    # ---- click outside to close: a see-through layer under the panel, on the island's monitor
    def _show_catcher(self):
        if getattr(self, "catcher", None) is None:
            c = Gtk.Window(application=self.get_application())
            c.add_css_class("islet-catcher")
            LS.init_for_window(c)
            LS.set_namespace(c, "islet-catcher")
            LS.set_layer(c, LS.Layer.TOP)  # under the island (OVERLAY), over normal windows
            for edge in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
                LS.set_anchor(c, edge, True)
            LS.set_exclusive_zone(c, -1)
            LS.set_keyboard_mode(c, LS.KeyboardMode.NONE)
            area = Gtk.Box(hexpand=True, vexpand=True)
            g = Gtk.GestureClick()
            g.set_button(0)
            g.connect("pressed", lambda *_: GLib.idle_add(self._outside_click))
            area.add_controller(g)
            c.set_child(area)
            self.catcher = c
        mon = self._monitor_by_name(self.conf.get("monitor"))
        if mon:
            LS.set_monitor(self.catcher, mon)
        self.catcher.set_default_size(1, 1)
        self.catcher.present()

    def _outside_click(self):
        if self.panel_open:
            self.close_panel()
        return False

    def _active_changed(self, *_):
        # focus went to another window (e.g. a click on the other monitor) -> close
        if self.is_active():
            self._was_active = True
        elif self.panel_open and getattr(self, "_was_active", False) and not self._dragging:
            GLib.timeout_add(120, lambda: (self.close_panel() if self.panel_open and not self.is_active() else None, False)[1])

    def _tick(self, _w, clock):
        now = time.time()
        self.t = clock.get_frame_time() / 1e6
        if now >= self._next_blink:
            ph = now - self._next_blink
            self.blink = max(0.0, 1 - abs(ph - 0.08) / 0.08) if ph < 0.16 else 0.0
            if ph >= 0.16:
                self._next_blink = now + random.uniform(2.5, 6)
        self._timer_tick(now)
        act = self.top_act()
        np = self.now_playing() if self.app_on("nowplaying") else None
        sig = (self.state(), self.mood(), self.text_rev.get_reveal_child(), np and np[0],
               self._act_text(act) if act else None, len(self.live_acts()))
        if sig != self._last_sig:
            self._last_sig = sig
            self.refresh()
        if now - self._slow_at > 0.12:
            self._slow_at = now
            if getattr(self, "_pill_pulse", False):
                self.pillbar.pulse()
            if self.panel_open:
                self.dash.update_tiles()
        self.pet.queue_draw()
        self.dot.queue_draw()
        if self.panel_open:
            self.dash.pet.queue_draw()
        if self._dragging and self._dragged and getattr(self, "_live", False) and not self._hopped:
            self._follow_cursor()
        self._layout()
        self._update_input_region()
        return True

    # ------------------------------------------------------------------ layout
    # The pill sits at a fixed spot (pill_x) and never moves when it grows, the panel opens,
    # or the window resizes: the window and the panel are placed around it.
    PAD = 14  # transparent room left of the pill for its shadow

    def _pill_x(self, geo):
        """Left edge of the pill. The saved spot is the pill's centre ("cx"), so it grows evenly
        to both sides and stays centred where you put it."""
        pw = self.pill.get_width() or 112
        cx = self.conf.get("cx")
        if cx is None and self.conf.get("x") is not None:  # older configs saved the left edge
            cx = int(self.conf["x"]) + 56
        if cx is None:
            cx = geo.width // 2
        x = int(cx) - pw // 2
        return int(min(max(self.PAD, x), max(self.PAD, geo.width - pw - 4)))

    def _set_cx(self, cx):
        self.conf["cx"] = int(cx)
        self.conf.pop("x", None)

    def _layout(self):
        if not hasattr(self, "dash"):
            return  # still building the window
        geo = self._monitor_geom()
        if not geo:
            return
        px = self._pill_x(geo)
        y = int(min(max(0, self.conf.get("margin_top", 6)), max(0, geo.height - 60)))
        pill_ms = pan_ms = 0
        win = px
        if self.panel_rev.get_visible():
            pw = self.pill.get_width() or 112
            P = self.dash.get_width() or self.dash.get_preferred_size()[1].width
            panx = int(min(max(self.PAD, px + pw / 2 - P / 2), max(self.PAD, geo.width - P - self.PAD)))
            win = min(px, panx)
            pill_ms, pan_ms = px - win, panx - win
        sig = (win - self.PAD, y, pill_ms, pan_ms)
        if sig == getattr(self, "_layout_sig", None):
            return
        self._layout_sig = sig
        LS.set_margin(self, LS.Edge.LEFT, max(0, win - self.PAD))
        LS.set_margin(self, LS.Edge.TOP, y)
        self.pill.set_margin_start(pill_ms)
        self.panel_rev.set_margin_start(pan_ms)

    def _follow_cursor(self):
        c = cursor_pos()
        geo = self._monitor_geom()
        if not c or not geo:
            return
        cx, cy = c
        if not (geo.x <= cx < geo.x + geo.width and geo.y <= cy < geo.y + geo.height):
            self._hop(cx, cy)
            return
        self._set_cx(cx - geo.x - self._grab[0] + self._grab_pw / 2)
        self.conf["margin_top"] = int(max(0, cy - geo.y - self._grab[1] - 2))

    def _update_input_region(self):
        surf = self.get_surface()
        dbg_once = getattr(self, "_dbg_region", None)
        if surf is None:
            return
        rects = []
        for w in (self.pill, self.dash if self.panel_rev.get_child_revealed() else None):
            if w is None:
                continue
            ok, b = w.compute_bounds(self)
            if ok:
                rects.append((int(b.get_x()), int(b.get_y()), int(math.ceil(b.get_width())), int(math.ceil(b.get_height()))))
        key = tuple(rects)
        if key == self._region:
            return
        self._region = key
        dbg("input-region", key)
        surf.set_input_region(cairo.Region([cairo.RectangleInt(*r) for r in rects]))

    # ================================================================== tiles: music, timer, updates
    def _media_position(self):
        while True:
            if self.panel_open and self.music.get("length"):
                try:
                    out = subprocess.run(self._pc("position"), capture_output=True, text=True, timeout=2).stdout
                    self.music["pos"] = float(out.strip())
                    vol = subprocess.run(self._pc("volume"), capture_output=True, text=True, timeout=2).stdout
                    self.music["volume"] = float(vol.strip())
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            time.sleep(1)

    def _music_loop(self):
        threading.Thread(target=self._media_follow, daemon=True).start()
        threading.Thread(target=self._media_position, daemon=True).start()
        while True:
            try:
                g = sources.running_game()
            except Exception:
                g = None
            if g and g[0] == "roblox":
                g = (g[0], self._roblox_title() or "Roblox")
            if not g:
                self.game = None
            elif not self.game or self.game["key"] != g[0]:
                self.game = {"key": g[0], "name": g[1], "since": time.time()}
                GLib.idle_add(lambda: (self.refresh(), False)[1])
            else:
                self.game["name"] = g[1]
            time.sleep(4)

    @staticmethod
    def _cached_art(url):
        """Web cover art (Spotify gives https URLs): download once, return a file:// URL ("" while loading)."""
        import hashlib
        import urllib.request
        d = os.path.expanduser("~/.cache/islet/art")
        path = os.path.join(d, hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
        if os.path.exists(path):
            return "file://" + path
        try:
            os.makedirs(d, exist_ok=True)
            with urllib.request.urlopen(url, timeout=6) as r, open(path + ".part", "wb") as f:
                f.write(r.read(5_000_000))
            os.replace(path + ".part", path)
            return "file://" + path
        except OSError:
            return ""

    def _media_follow(self):
        """playerctl --follow prints a line the moment a song/video starts, pauses or changes."""
        fmt = "{{status}}\t{{title}}\t{{artist}}\t{{playerName}}\t{{mpris:artUrl}}\t{{mpris:length}}"
        while True:
            try:
                p = subprocess.Popen(["playerctl", "--follow", "metadata", "--format", fmt],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     preexec_fn=_die_with_parent)
            except OSError:
                return
            for line in p.stdout:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4 and parts[1]:
                    m = dict(zip(("status", "title", "artist", "player", "art", "length"), parts))
                    try:
                        m["length"] = int(m.get("length") or 0) / 1e6 or None
                    except ValueError:
                        m["length"] = None
                    m["pos"] = self.music.get("pos") if self.music.get("title") == m["title"] else None
                    m["volume"] = self.music.get("volume") if self.music.get("player") == m.get("player") else None
                    if m.get("art", "").startswith("http"):
                        m["art"] = self._cached_art(m["art"])
                    self.music = m
                else:
                    self.music = {}
                GLib.idle_add(lambda: (self.refresh(), False)[1])
            p.wait()
            self.music = {}
            time.sleep(2)

    @staticmethod
    def _roblox_title():
        try:
            out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=2).stdout
            for c in json.loads(out):
                if "sober" in c.get("class", "").lower():
                    t = c.get("title", "").strip()
                    if t and t.lower() not in ("sober", "roblox"):
                        return f"Roblox · {t}"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None

    def now_playing(self):
        """(text, mood) for the idle pill: the game you're in, or what's playing."""
        if self.game:
            mins = int((time.time() - self.game["since"]) // 60)
            took = f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins} min"
            return f"🎮 {self.game['name']} · {took}", "focus"
        m = self.music
        if m.get("status") == "Playing" and m.get("title"):
            who = f" · {m['artist']}" if m.get("artist") else ""
            music_app = m.get("player", "").lower() in ("spotify", "cider", "tidal-hifi", "rhythmbox", "lollypop", "amberol")
            return f"▶ {m['title']}{who}", "happy" if music_app else "focus"
        return None

    def _pc(self, *args):
        """playerctl aimed at the player the island shows (else it picks one on its own, e.g. a paused tab)."""
        name = (self.music.get("player") or "").strip()
        return ["playerctl", "-p", name, *args] if name else ["playerctl", *args]

    def _playerctl(self, *args):
        try:
            subprocess.Popen(self._pc(*args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        if self.music:
            st = self.music.get("status")
            if args == ("play-pause",):
                self.music["status"] = "Paused" if st == "Playing" else "Playing"

    BROWSERS = ("firefox", "librewolf", "chromium", "brave", "chrome", "vivaldi", "zen")

    def video_url(self):
        """The browser video's URL, or None (music apps, nothing playing)."""
        if self.music.get("player", "").split(".")[0] not in self.BROWSERS:
            return None
        try:
            url = subprocess.run(self._pc("metadata", "xesam:url"), capture_output=True, text=True,
                                 timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return url if url.startswith("http") else None

    def mini_open(self):
        m = getattr(self, "mini", None)
        return m is not None and m.get_visible() and bool(m.mp.h)

    def music_toggle(self):
        """Music tile click: open the Now Playing page."""
        self.dash.show("media")

    def pop_out(self):
        url = self.video_url()
        if url:
            self.open_mini(url)

    # media controls: the mini player while it's open, otherwise the browser/music app (playerctl)
    def media(self, action, value=None):
        if self.mini_open():
            mp = self.mini.mp
            if action == "toggle":
                mp.cmd("cycle", "pause")
            elif action == "back":
                mp.cmd("seek", "-10")
            elif action == "fwd":
                mp.cmd("seek", "10")
            elif action == "seek":
                mp.cmd("seek", f"{value:.1f}", "absolute")
            elif action == "volume":
                mp.set("volume", int(value * 100))
            elif action == "close":
                self.mini.close_player()
            elif action == "browser":
                self.mini.back_to_browser()
            return
        if action == "toggle":
            self._playerctl("play-pause")
        elif action == "back":
            self._playerctl("position", "10-")
        elif action == "fwd":
            self._playerctl("position", "10+")
        elif action in ("previous", "next"):
            self._playerctl(action)
        elif action == "seek":
            self._playerctl("position", f"{value:.1f}")
            self.music["pos"] = value
        elif action == "volume":
            self._playerctl("volume", f"{value:.2f}")

    def media_state(self):
        """(pos, length, playing, volume 0..1, where) for the Now Playing page."""
        if self.mini_open():
            mp = self.mini.mp
            vol = mp.getf("volume")
            return (mp.getf("time-pos"), mp.getf("duration"), mp.get("pause") != "yes",
                    (vol or 0) / 100, "mini")
        m = self.music
        return m.get("pos"), m.get("length"), m.get("status") == "Playing", m.get("volume"), "app"

    def open_mini(self, url):
        import miniplayer
        if getattr(self, "mini", None) is not None and self.mini.get_visible():
            self.mini.close_player()
        try:
            pos = float(subprocess.run(self._pc("position"), capture_output=True, text=True, timeout=2).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            pos = 0.0
        browser = self.music.get("player") or ""
        subprocess.Popen(self._pc("pause"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.mini = miniplayer.MiniPlayer(self.get_application(), url, pos, self.music.get("title", "Video"),
                                              self._monitor_by_name(self.conf.get("monitor")), self.conf, save_conf,
                                              cursor_pos, self.conf.get("accent", "#ff8fc7"), browser)
        except Exception as e:  # missing libmpv etc.: don't take the island down
            self.mini = None
            self.alert("ask", "Mini player failed", str(e), quiet=True)
            subprocess.Popen(self._pc("play"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if self.panel_open:
            GLib.timeout_add(200, lambda: (self.dash.show("media"), False)[1])

    def music_next(self):
        self._playerctl("next")

    def timer_text(self):
        if self.timer_end:
            left = max(0, self.timer_end - time.time())
        elif self.timer_left is not None:
            left = self.timer_left
        else:
            left = self.conf.get("timer_min", 25) * 60
        return f"{int(left // 60)}:{int(left % 60):02d}"

    def timer_sub(self):
        if self.timer_end:
            return "Running · right-click resets"
        if self.timer_left is not None:
            return "Paused · click to resume"
        return "Timer · click, scroll to set"

    def timer_click(self):
        now = time.time()
        if self.timer_end:
            self.timer_left = max(0, self.timer_end - now)
            self.timer_end = None
            self.post_activity("timer", "main", {"title": "Timer paused", "detail": self.timer_text(),
                                                 "color": "#ffa94d", "mood": "sleepy"})
        else:
            secs = self.timer_left if self.timer_left is not None else self.conf.get("timer_min", 25) * 60
            self.timer_total = self.conf.get("timer_min", 25) * 60
            self.timer_end = now + secs
            self.timer_left = None
            self.post_activity("timer", "main", {"title": "Timer", "until": self.timer_end,
                                                 "total": self.timer_total, "color": "#ffa94d", "mood": "focus"})

    def timer_reset(self):
        self.timer_end = None
        self.timer_left = None
        self.post_activity("timer", "main", None)

    def timer_adjust(self, d):
        if self.timer_end or self.timer_left is not None:
            return
        m = self.conf.get("timer_min", 25)
        m = max(1, min(180, m + d * (1 if m < 5 or (m == 5 and d < 0) else 5)))
        self.conf["timer_min"] = m
        save_conf(self.conf)

    def _timer_tick(self, now):
        if self.timer_end and now >= self.timer_end:
            self.timer_end = None
            self.timer_left = None
            self.post_activity("timer", "main", {"title": "Time's up!", "detail": f"{self.conf.get('timer_min', 25)} min",
                                                 "color": "#ffa94d", "mood": "happy", "ttl": 8, "flash": True})
            self._override("happy", 5)
            self.alert("done", "Islet timer", "Time's up!", force=True, show=False)

    def _first_update_check(self):
        if self.app_on("updates"):
            self.updates.check()
        return False

    def _updates_changed(self):
        u = self.updates
        if u.running:
            self.post_activity("updates", "run", {"title": "Updating", "detail": "in the terminal", "color": "#66d9e8",
                                                  "mood": "focus", "pulse": True})
        else:
            self.post_activity("updates", "run", None)
        sig = (u.total, u.checked)
        if u.checked and sig != self._upd_seen:
            first = self._upd_seen is None
            self._upd_seen = sig
            if u.total and not first:
                self.alert("ask", "Updates available", u.summary())
        self.refresh()
        return False

    def run_action(self, a):
        self.runner.toggle(a)
        GLib.timeout_add(150, lambda: (self.dash.refresh(), False)[1])

    def run_update(self, mode):
        if not self.updates.run(self.conf, mode):
            self.alert("ask", "Islet", "Couldn't start the update (no terminal found?)", force=True)

    def _auto_update(self):
        c = self.conf
        if not c.get("auto_update") or not self.app_on("updates"):
            return
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        if c.get("last_auto") == today:
            return
        if (now.hour, now.minute) >= (int(c.get("auto_hour", 20)), int(c.get("auto_min", 0))):
            c["last_auto"] = today
            save_conf(c)
            self.run_update(int(c.get("auto_mode", 0)))

    # ================================================================== dragging
    def _place(self):
        LS.set_anchor(self, LS.Edge.TOP, True)
        LS.set_anchor(self, LS.Edge.LEFT, True)
        self._layout_sig = None
        self._layout()

    @staticmethod
    def monitors():
        """Monitors left to right (Monitor 1 is the leftmost)."""
        ms = Gdk.Display.get_default().get_monitors()
        out = [ms.get_item(i) for i in range(ms.get_n_items())]
        return sorted(out, key=lambda m: (m.get_geometry().x, m.get_geometry().y))

    def current_monitor_name(self):
        if self._monitor_by_name(self.conf.get("monitor")):
            return self.conf["monitor"]
        surf = self.get_surface()
        mon = surf and Gdk.Display.get_default().get_monitor_at_surface(surf)
        return mon.get_connector() if mon else None

    def next_monitor(self):
        names = [m.get_connector() for m in self.monitors()]
        if len(names) < 2:
            return
        cur = self.current_monitor_name()
        nxt = names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]
        self.move_to_monitor(nxt)

    def _monitor_by_name(self, name):
        mons = self.monitors()
        if isinstance(name, str) and name.isdigit() and 1 <= int(name) <= len(mons):
            return mons[int(name) - 1]  # "1", "2": numbered left to right
        return next((m for m in mons if name and m.get_connector() == name), None)

    def move_to_monitor(self, name, x=None, y=None):
        mon = self._monitor_by_name(name)
        if not mon:
            return False
        name = mon.get_connector()
        self.conf["monitor"] = name
        if x is not None:
            self._set_cx(int(x) + (self.pill.get_width() or 112) / 2)
            self.conf["margin_top"] = int(y)
        save_conf(self.conf)
        # A mapped layer surface doesn't come back by itself after a monitor change:
        # hide it, switch, show it again (after the current drag/click event is done).
        def swap():
            self._auto_x = None
            self.set_visible(False)
            LS.set_monitor(self, mon)
            self._place()
            self._region = None
            self.set_visible(True)
            self.present()
            return False
        GLib.idle_add(swap)
        return True

    def _hop(self, gx, gy):
        """The pointer left this monitor while dragging: move to the monitor under it."""
        cur = self._monitor_geom()
        for m in self.monitors():
            g = m.get_geometry()
            if cur and (g.x, g.y) == (cur.x, cur.y):
                continue
            if g.x <= gx < g.x + g.width and g.y <= gy < g.y + g.height:
                x = gx - g.x - self._grab[0]
                y = max(0, gy - g.y - self._grab[1] - 2)
                self._hopped = True
                self.move_to_monitor(m.get_connector(), x, y)
                return True
        return False

    def _monitor_geom(self):
        # Trust the monitor we put ourselves on: right after a switch GTK still reports the old one.
        mon = self._monitor_by_name(self.conf.get("monitor"))
        if mon is None:
            surf = self.get_surface()
            mon = surf and Gdk.Display.get_default().get_monitor_at_surface(surf)
            if mon:
                self.conf["monitor"] = mon.get_connector()
        return mon.get_geometry() if mon else None

    def _drag_begin(self, _g, x, y):
        dbg("drag-begin", x, y)
        self._dragging, self._dragged, self._hopped = True, False, False
        self._grab = (x, y)  # where on the pill the pointer is
        self._grab_pw = self.pill.get_width() or 112
        self._live = cursor_pos() is not None  # follow Hyprland's cursor every frame

    def _drag_update(self, _g, ox, oy):
        if not self._dragged and abs(ox) + abs(oy) < 6:
            return
        if not self._dragged:
            geo = self._monitor_geom()
            if geo:  # a real drag: make the current spot explicit
                self._set_cx(self._pill_x(geo) + (self.pill.get_width() or 112) / 2)
        self._dragged = True
        if self._hopped or self._live:
            return  # live mode moves it in _follow_cursor, once per frame
        # other compositors: offsets are relative to a surface that moves with us, so add them up
        self._set_cx(self.conf["cx"] + ox)
        self.conf["margin_top"] = int(max(0, self.conf["margin_top"] + oy))

    def _drag_end(self, _g, ox, oy):
        dbg("drag-end", ox, oy, "dragged", self._dragged)
        self._dragging = False
        if self._dragged and not self._hopped:
            if self._live:
                self._follow_cursor()
            geo = self._monitor_geom()
            if geo:
                self._set_cx(self._pill_x(geo) + (self.pill.get_width() or 112) / 2)
            save_conf(self.conf)
        if self._dragged:
            GLib.timeout_add(80, self._clear_dragged)

    def _simdrag(self, msg):
        """Debug: replay a drag with a fake cursor, from (x1,y1) to (x2,y2) global, over secs."""
        global FAKE_CURSOR
        x1, y1, x2, y2 = (float(msg[k]) for k in ("x1", "y1", "x2", "y2"))
        secs = float(msg.get("secs", 1.0))
        t0 = time.time()

        def fake():
            f = min(1.0, (time.time() - t0) / secs)
            return int(x1 + (x2 - x1) * f), int(y1 + (y2 - y1) * f)
        FAKE_CURSOR = fake
        self._drag_begin(None, 20, 20)
        self._drag_update(None, 10, 0)

        def finish():
            global FAKE_CURSOR
            if self._dragging:
                self._drag_end(None, 0, 0)
            FAKE_CURSOR = None
            dbg("simdrag done", self.conf.get("monitor"), self.conf.get("cx"), self.conf.get("margin_top"))
            return False
        GLib.timeout_add(int(secs * 1000) + 200, finish)

    def _clear_dragged(self):
        self._dragged = False
        return False

    def reset_position(self):
        self._auto_x = None
        self.conf["x"] = None
        self.conf["cx"] = None
        self.conf["margin_top"] = DEFAULT_CONF["margin_top"]
        save_conf(self.conf)
        self._place()

    # ================================================================== interaction
    def _set_hover(self, v):
        self.hover = v
        self.refresh()

    def _pill_click(self, gesture, n, x, y):
        dbg("click-released", n, x, y, "dragged", self._dragged, "open", self.panel_open)
        if self._dragged:
            return
        w = self.pill.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not self.pill:
            if isinstance(w, (Gtk.Button, Pet)):
                return
            w = w.get_parent()
        if self.panel_open:
            self.close_panel()
        else:
            self.open_panel()

    def _poke(self, gesture, n, x, y):
        now = time.time()
        if n == 2:
            self._override("love", 2.5)
            return
        self.pokes.append(now)
        if len([p for p in self.pokes if now - p < 2.5]) >= 5:
            self.pokes.clear()
            self._override("dizzy", 3.5)
        else:
            self._override("wink", 0.8)

    def _override(self, mood, secs):
        self.override_mood = mood
        self.override_until = time.time() + secs

    def pet_name(self, sp=None):
        sp = sp or self.conf.get("pet", "pup")
        return (self.conf.get("pet_names") or {}).get(sp) or {"pup": "Puppy", "kitty": "Kitty"}.get(sp, "Pip")

    def set_pet(self, sp):
        self.conf["pet"] = sp
        save_conf(self.conf)
        self._override("happy", 1.5)
        self.refresh()

    def toggle_app(self, app):
        self.conf.setdefault("apps", {})[app] = not self.app_on(app)
        save_conf(self.conf)
        self.refresh()

    def answer(self, decision):
        if not self.pending:
            return
        pd = self.pending.pop(0)
        self._reply(pd.conn, decision)
        pd.sess.log({"allow": f"Allowed: {pd.label}", "deny": f"Denied: {pd.label}"}.get(decision, "Answer in terminal"),
                    "working" if decision in ("allow", "deny") else "question")
        self.refresh()

    def _drop_pending(self, pid):
        gone = [p for p in self.pending if p.id == pid]
        self.pending = [p for p in self.pending if p.id != pid]
        for p in gone:
            p.sess.log("Answered in terminal", "working")
        if gone:
            self.refresh()
        return False

    def welcome(self, force=False):
        """Once per login (marker in $XDG_RUNTIME_DIR, which is cleared at logout/reboot): a hello."""
        marker = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "islet-welcomed")
        if not force and (not self.conf.get("welcome", True) or os.path.exists(marker)):
            return False
        try:
            open(marker, "w").close()
        except OSError:
            pass
        name = model.user_name(self.conf)
        for player in ("pw-play", "paplay"):
            try:
                subprocess.Popen([player, os.path.join(DATA, "sounds", "hello.wav")],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except OSError:
                continue
        self.alert("done", f"{model.greeting()}, {name}! 🐾", f"{self.pet_name()} missed you",
                   quiet=True, color=self.conf.get("accent"))
        self._override("love", 5)
        return False

    def _ensure_shown(self):
        if not self.get_mapped():
            self._region = None
            self.set_visible(True)
            self.present()
        return True

    def _sweep(self):
        now = time.time()
        for s in list(self.sessions.values()):
            if s.state == "working" and now - s.updated > 600:
                s.state = "idle"
            if now - s.updated > 6 * 3600:
                del self.sessions[s.sid]
        if self.app_on("updates"):
            self.updates.maybe_check(float(self.conf.get("upd_every_h", 3)))
            self._auto_update()
        self.refresh()
        return True

    # ================================================================== activities + alerts
    def post_activity(self, app, aid, act):
        key = f"{app}:{aid}"
        if act is None:
            self.activities.pop(key, None)
        else:
            old = self.activities.get(key)
            act = dict(act, app=app, id=aid)
            for k in ("title", "detail"):
                if isinstance(act.get(k), str) and "{pet}" in act[k]:
                    act[k] = act[k].replace("{pet}", self.pet_name())
            if act.get("toast") and not old:
                self.inbox.appendleft({"t": time.time(), "kind": "info", "title": act["title"],
                                       "body": act.get("detail", ""), "color": act.get("color")})
            act["added"] = old["added"] if old and not act.get("flash") and not old.get("flash") else time.time()
            if act.get("ttl"):
                act["until"] = time.time() + float(act["ttl"])
            self.activities[key] = act
            if act.get("notify") and not old and self.app_on(app):
                self.alert("done", act["title"], act.get("detail", ""), show=False)
        self.refresh()
        return False

    def alert(self, kind, title, body, force=False, show=True, quiet=False, color=None, app=None):
        """Chime + an in-island toast (+ a system popup only if turned on in Settings)."""
        if (self.conf.get("sound") and not quiet) or force:
            wav = os.path.join(DATA, "sounds", "done.wav" if kind == "done" else "ask.wav")
            for player in ("pw-play", "paplay"):
                try:
                    subprocess.Popen([player, wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except OSError:
                    continue
        body = _first_line(body, 160)
        self.inbox.appendleft({"t": time.time(), "kind": kind, "title": title, "body": body, "color": color})
        if show:
            self._toast_n += 1
            col = color or ("#9be36b" if kind == "done" else "#ffd23c")
            self.post_activity("toast", str(self._toast_n), {
                "title": title, "detail": body, "color": col, "mood": "curious" if kind == "ask" else "happy",
                "ttl": 3.5 if quiet else 6, "flash": True, "toast": True})
        if self.conf.get("desktop_notify"):
            icon = os.path.join(DATA, f"{self.conf['pet']}.png")
            try:
                subprocess.Popen(["notify-send", "-a", "Islet", "-i", icon, title, body],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    # ================================================================== socket messages
    def on_event(self, msg, conn):
        if msg.get("cmd"):
            conn.close()
            cmd = msg["cmd"]
            if cmd == "answer":
                self.answer(msg.get("decision", "ask"))
            elif cmd == "pet" and msg.get("pet") in pip.PETS:
                self.set_pet(msg["pet"])
            elif cmd == "push" and msg.get("app") and msg.get("title"):
                act = {k: msg[k] for k in ("title", "detail", "color", "mood", "ttl") if msg.get(k) is not None}
                if msg.get("progress") not in (None, ""):
                    try:
                        act["progress"] = max(0.0, min(1.0, float(msg["progress"])))
                    except ValueError:
                        pass
                self.post_activity(msg["app"], msg.get("id") or "main", act)
            elif cmd == "clear" and msg.get("app"):
                for k in [k for k, a in self.activities.items()
                          if a["app"] == msg["app"] and (not msg.get("id") or a["id"] == msg["id"])]:
                    del self.activities[k]
                self.refresh()
            elif cmd == "simdrag" and DEBUG:
                self._simdrag(msg)
            elif cmd == "monitor":
                if msg.get("name") == "next":
                    self.next_monitor()
                else:
                    self.move_to_monitor(msg.get("name"))
            elif cmd == "center":
                self.reset_position()
            elif cmd == "toggle":
                self.close_panel() if self.panel_open else self.open_panel()
            elif cmd == "open":
                self.open_panel(msg.get("page") or "home")
            elif cmd == "run":
                a = next((a for a in self.conf.get("actions", []) if a["name"] == msg.get("name")), None)
                if a:
                    self.runner.toggle(a)
            elif cmd == "toast" and msg.get("title"):
                # other apps' notifications (hyprclick ON/OFF, errors): quiet toast, shown if that app is on
                app = msg.get("app") or "app"
                if self.app_on(app):
                    self.alert("info", str(msg["title"]), str(msg.get("body") or ""), quiet=True,
                               color=msg.get("color") or "#a0e0ff", app=app)
            elif cmd == "welcome":
                self.welcome(force=True)
            elif cmd == "mini":
                self.pop_out()
            elif cmd == "check-updates":
                self.updates.check()
            return False
        src = msg.get("src", "claude")
        ev = msg.get("ev") or {}
        if not self.app_on(src):
            if conn is not None:
                if ev.get("hook_event_name") == "PermissionRequest":
                    self._reply(conn, "ask")
                else:
                    conn.close()
            return False
        name = ev.get("hook_event_name", "")
        sid = str(ev.get("session_id") or ev.get("thread_id") or f"{src}:{ev.get('cwd', '')}")
        cwd = ev.get("cwd") or ""
        s = self.sessions.get(sid)
        if s is None:
            if name == "SessionEnd":
                if conn:
                    conn.close()
                return False
            s = self.sessions[sid] = Session(sid, src, cwd)
        if cwd:
            s.cwd = cwd
        tool, inp = ev.get("tool_name"), ev.get("tool_input")

        if name == "SessionStart":
            s.log("Session started", "idle")
        elif name == "UserPromptSubmit":
            s.answer = ""
            s.log("Thinking: " + _first_line(ev.get("prompt"), 60), "working")
        elif name == "PreToolUse":
            s.log(describe(tool, inp), "working")
            code = highlight.code_from_tool(tool, inp)
            if code:
                code["t0"] = time.time()
                code["label"] = describe(tool, inp)
                s.code = code
        elif name == "PostToolUse":
            s.updated = time.time()
            if s.state != "question":
                s.state = "working"
        elif name == "PermissionRequest":
            if tool in NO_BLOCK_TOOLS:
                self._reply(conn, "ask")
                s.log("Has a question for you", "question")
                self.alert("ask", f"{s.agent} · {s.project}", "Has a question for you")
            else:
                label = describe(tool, inp, perm=True)
                s.log(f"Waiting: {label}", "question")
                pd = Pending(conn, s, label)
                self.pending.append(pd)
                threading.Thread(target=self._watch, args=(pd,), daemon=True).start()
                self.alert("ask", f"{s.agent} · {s.project}", f"Allow: {label}?", show=False)
            conn = None
        elif name == "Notification":
            typ = ev.get("notification_type", "")
            m = ev.get("message", "")
            if typ == "permission_prompt" and not any(p.sess is s for p in self.pending):
                s.log(m or "Needs permission", "question")
                self.alert("ask", f"{s.agent} · {s.project}", m or "Needs permission")
            elif typ not in ("permission_prompt", "idle_prompt") and m:
                s.log(m)
        elif name == "Stop":
            s.answer = last_assistant_text(ev)
            s.done_at = time.time()
            s.log("Done", "done")
            self._override("happy", 4)
            self.alert("done", f"{s.agent} · {s.project} is done", _first_line(s.answer, 200) or "Finished")
        elif name == "SessionEnd":
            for p in [p for p in self.pending if p.sess is s]:
                self.pending.remove(p)
                self._reply(p.conn, "ask")
            self.sessions.pop(sid, None)
        if conn is not None:
            conn.close()
        self.refresh()
        return False

    @staticmethod
    def _reply(conn, decision):
        try:
            conn.sendall((json.dumps({"decision": decision}) + "\n").encode())
            conn.close()
        except OSError:
            pass

    def _watch(self, pd):
        try:
            while pd.conn.recv(64):
                pass
        except OSError:
            pass
        GLib.idle_add(self._drop_pending, pd.id)


# =========================================================================== socket server

def _log_event(line):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2_000_000:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write(line.strip() + "\n")
    except OSError:
        pass


def serve(island):
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o600)
    srv.listen(16)

    def handle(conn):
        buf = b""
        conn.settimeout(3)
        try:
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            conn.close()
            return
        conn.settimeout(None)
        line = buf.decode("utf-8", "replace")
        if not line.strip():
            conn.close()
            return
        _log_event(line)
        try:
            msg = json.loads(line)
        except ValueError:
            conn.close()
            return
        GLib.idle_add(island.on_event, msg, conn)

    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


def _already_running():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCK)
        s.close()
        return True
    except OSError:
        return False


def main():
    if _already_running():
        print("islet is already running")
        return 2
    ensure_assets()
    app = Gtk.Application(application_id="dev.ari.islet")

    def activate(a):
        win = Island(a)
        win.present()
        threading.Thread(target=serve, args=(win,), daemon=True).start()
        post = lambda app_, aid, act: GLib.idle_add(win.post_activity, app_, aid, act)  # noqa: E731
        sources.Watchers(post, win.app_on).start()
        sources.CommandWatch(post, lambda: list(win.conf.get("custom", [])), win.app_on).start()

    app.connect("activate", activate)
    return app.run([])
