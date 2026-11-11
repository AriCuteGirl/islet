"""Islet dashboard: the panel under the pill. Home (agent card + tiles + live activities),
Updates, and Settings pages."""
import os
import shutil
import subprocess
import time

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

import actions as acts_mod
import highlight
import pets as pip
import updates as upd
from model import user_name as model_user_name
from model import ACCENTS, COLORS, SOURCES, _first_line, save_conf

# Symbols Nerd Font glyphs
I = {
    "home": "\U000F02DC", "plus": "\U000F0415", "vol": "\U000F057E", "mute": "\U000F0581",
    "cog": "\U000F0493", "up": "\U000F0143", "music": "\U000F0386", "play": "\U000F040A",
    "pause": "\U000F03E4", "timer": "\U000F051B", "clock": "\U000F0954", "pkg": "\U000F03D3",
    "click": "\U000F0CFD", "check": "\U000F012C", "left": "\U000F0141", "right": "\U000F0142",
    "close": "\U000F0156", "dot": "\U000F09DE", "q": "\U000F02D7", "steam": "\U000F04D3",
    "dl": "\U000F01DA", "prev": "\U000F04AE", "next": "\U000F04AD", "rew": "\U000F045F", "ffw": "\U000F0211",
    "popout": "\U000F05C3", "web": "\U000F059F", "bell": "\U000F009A", "monitor": "\U000F0379", "refresh": "\U000F0450", "term": "\U000F018D",
}

CSS = """
.panel {
  background-image: linear-gradient(180deg, #121216, #08080a);
  color: #eee; border-radius: 26px; padding: 12px 14px 14px 14px;
  border: 1px solid alpha(white, 0.08);
  box-shadow: 0 0 26px alpha(@accent, 0.16), 0 12px 32px alpha(black, 0.65);
}
.ico { font-family: "Symbols Nerd Font", "Symbols Nerd Font Mono"; }
button.hbtn { background: none; border: none; box-shadow: none; color: alpha(white, 0.6);
  min-width: 30px; min-height: 30px; padding: 0; border-radius: 10px; font-size: 16px;
  transition: all 150ms ease; }
button.hbtn:hover { background: alpha(white, 0.08); color: white; }
button.hbtn.on { background: alpha(@accent, 0.18); color: @accent; }
.maincard { padding: 14px; border-radius: 20px; border: 1px solid alpha(@accent, 0.18);
  background-image: linear-gradient(160deg, alpha(@accent, 0.13), alpha(white, 0.025) 60%); }
.tile { padding: 10px 12px; min-width: 156px; min-height: 54px; border-radius: 18px;
  border: 1px solid alpha(white, 0.06); background: alpha(white, 0.04); transition: all 160ms ease; }
.actcard { background: alpha(white, 0.045); border-radius: 16px; padding: 9px 12px;
  border: 1px solid alpha(white, 0.06); }
.actcard:hover { background: alpha(white, 0.075); }
.bubble { border-radius: 13px; min-width: 38px; min-height: 38px; font-size: 18px; color: #101014; }
.art { border-radius: 11px; }
.artbox { border-radius: 11px; box-shadow: 0 3px 12px alpha(black, 0.5); }
.tile.t-music { background-image: linear-gradient(135deg, alpha(#9be36b, 0.17), alpha(#9be36b, 0.035)); border-color: alpha(#9be36b, 0.20); }
.tile.t-music:hover { background-image: linear-gradient(135deg, alpha(#9be36b, 0.28), alpha(#9be36b, 0.07)); border-color: alpha(#9be36b, 0.40); }
.b-music { background-image: linear-gradient(160deg, #a8ef7c, #5fc22f); box-shadow: 0 3px 12px alpha(#9be36b, 0.40); }
.t-music .bar progress { background: #9be36b; }
.tile.t-timer { background-image: linear-gradient(135deg, alpha(#ffa94d, 0.17), alpha(#ffa94d, 0.035)); border-color: alpha(#ffa94d, 0.20); }
.tile.t-timer:hover { background-image: linear-gradient(135deg, alpha(#ffa94d, 0.28), alpha(#ffa94d, 0.07)); border-color: alpha(#ffa94d, 0.40); }
.b-timer { background-image: linear-gradient(160deg, #ffc078, #ff8a2a); box-shadow: 0 3px 12px alpha(#ffa94d, 0.40); }
.t-timer .bar progress { background: #ffa94d; }
.tile.t-clock { background-image: linear-gradient(135deg, alpha(#7aa2ff, 0.17), alpha(#7aa2ff, 0.035)); border-color: alpha(#7aa2ff, 0.20); }
.tile.t-clock:hover { background-image: linear-gradient(135deg, alpha(#7aa2ff, 0.28), alpha(#7aa2ff, 0.07)); border-color: alpha(#7aa2ff, 0.40); }
.b-clock { background-image: linear-gradient(160deg, #9db8ff, #5a7cff); box-shadow: 0 3px 12px alpha(#7aa2ff, 0.40); }
.t-clock .bar progress { background: #7aa2ff; }
.tile.t-upd { background-image: linear-gradient(135deg, alpha(#66d9e8, 0.17), alpha(#66d9e8, 0.035)); border-color: alpha(#66d9e8, 0.20); }
.tile.t-upd:hover { background-image: linear-gradient(135deg, alpha(#66d9e8, 0.28), alpha(#66d9e8, 0.07)); border-color: alpha(#66d9e8, 0.40); }
.b-upd { background-image: linear-gradient(160deg, #8ae6f0, #2fb8c9); box-shadow: 0 3px 12px alpha(#66d9e8, 0.40); }
.t-upd .bar progress { background: #66d9e8; }
.tile.t-click { background-image: linear-gradient(135deg, alpha(#c79bff, 0.17), alpha(#c79bff, 0.035)); border-color: alpha(#c79bff, 0.20); }
.tile.t-click:hover { background-image: linear-gradient(135deg, alpha(#c79bff, 0.28), alpha(#c79bff, 0.07)); border-color: alpha(#c79bff, 0.40); }
.b-click { background-image: linear-gradient(160deg, #d9b6ff, #a46cf5); box-shadow: 0 3px 12px alpha(#c79bff, 0.40); }
.t-click .bar progress { background: #c79bff; }
.tile.t-cog { background-image: linear-gradient(135deg, alpha(#ff8fc7, 0.17), alpha(#ff8fc7, 0.035)); border-color: alpha(#ff8fc7, 0.20); }
.tile.t-cog:hover { background-image: linear-gradient(135deg, alpha(#ff8fc7, 0.28), alpha(#ff8fc7, 0.07)); border-color: alpha(#ff8fc7, 0.40); }
.b-cog { background-image: linear-gradient(160deg, #ffb3d9, #ff6fb3); box-shadow: 0 3px 12px alpha(#ff8fc7, 0.40); }
.t-cog .bar progress { background: #ff8fc7; }
.tt { font-weight: 800; font-size: 14px; }
.t-clock .tt, .t-timer .tt { font-size: 19px; font-weight: 900; }
.ts { color: alpha(white, 0.55); font-size: 11px; }
.big { font-weight: 800; font-size: 20px; }
.greet { font-weight: 900; font-size: 18px; }
.proj { font-weight: 800; font-size: 14px; }
.agentlbl { color: alpha(white, 0.45); font-size: 11px; font-weight: 700; }
.status { font-weight: 800; font-size: 12px; }
.chip { background: alpha(white, 0.07); border-radius: 999px; padding: 3px 10px; font-size: 11px; font-weight: 700;
  color: alpha(white, 0.8); }
.chip.hot { background: alpha(@accent, 0.2); color: @accent; }
.answerbox { background: alpha(black, 0.4); border-radius: 12px; padding: 8px 10px;
  font-family: monospace; font-size: 11px; color: alpha(white, 0.8); border: 1px solid alpha(white, 0.05); }
button.mini { background: none; border: none; box-shadow: none; padding: 0 4px; min-height: 18px; min-width: 18px; color: alpha(white, 0.6); }
button.mini:hover { color: white; }
.bar trough { min-height: 4px; background: alpha(white, 0.1); border-radius: 3px; }
.bar progress { min-height: 4px; background: @accent; border-radius: 3px; }
.tbar trough { min-height: 3px; background: alpha(white, 0.1); border-radius: 2px; }
.tbar progress { min-height: 3px; background: #9be36b; border-radius: 2px; }
.pagetitle { font-weight: 900; font-size: 17px; }
.section { font-size: 11px; font-weight: 800; color: alpha(white, 0.4); margin-top: 8px; letter-spacing: 1px; }
.srow { background: alpha(white, 0.04); border-radius: 14px; padding: 6px 12px; border: 1px solid alpha(white, 0.05); }
.hint { color: alpha(white, 0.45); font-size: 11px; }
.mono { font-family: monospace; font-size: 11px; color: alpha(white, 0.7); }
button.act { border-radius: 999px; padding: 4px 16px; border: none; box-shadow: none; font-weight: 800;
  background: alpha(white, 0.09); color: #eee; transition: all 150ms ease; }
button.act:hover { background: alpha(white, 0.16); }
button.act.primary { background-image: linear-gradient(160deg, shade(@accent, 1.15), @accent); color: #101014;
  box-shadow: 0 3px 12px alpha(@accent, 0.35); }
button.act.primary:hover { background-image: linear-gradient(160deg, shade(@accent, 1.25), shade(@accent, 1.05)); }
button.pet { border-radius: 999px; padding: 3px 12px; background: alpha(white, 0.07); border: none; box-shadow: none;
  color: #ddd; font-weight: 700; }
button.pet:hover { background: alpha(white, 0.12); }
button.pet.on { background: @accent; color: #101014; }
button.swatch { min-width: 24px; min-height: 24px; border-radius: 999px; padding: 0; border: 2px solid transparent; box-shadow: none; }
button.swatch.on { border-color: white; }
switch { background: alpha(white, 0.12); border: none; border-radius: 999px; }
switch:checked { background: @accent; }
switch slider { background: white; border: none; box-shadow: 0 1px 4px alpha(black, 0.4); border-radius: 999px; }
entry, spinbutton { background: alpha(white, 0.06); color: #eee; border: 1px solid alpha(white, 0.08); border-radius: 10px; min-height: 30px; }
entry:focus-within, spinbutton:focus-within { border-color: alpha(@accent, 0.6); }
.empty { color: alpha(white, 0.45); font-size: 12px; }
.bigart { border-radius: 16px; background: alpha(white, 0.05); box-shadow: 0 6px 20px alpha(black, 0.5); }
.mtitle { font-weight: 900; font-size: 17px; }
button.mctl { background: alpha(white, 0.08); border: none; box-shadow: none; color: white; border-radius: 999px;
  min-width: 38px; min-height: 38px; padding: 0; font-size: 17px; transition: all 140ms ease; }
button.mctl:hover { background: alpha(white, 0.16); }
button.mctl:disabled { color: alpha(white, 0.25); }
button.mctl.big { min-width: 50px; min-height: 50px; font-size: 22px; color: #101014;
  background-image: linear-gradient(160deg, shade(@accent, 1.15), @accent); box-shadow: 0 4px 14px alpha(@accent, 0.4); }
scale.mseek trough { min-height: 5px; background: alpha(white, 0.12); border-radius: 3px; }
scale.mseek highlight { background: @accent; border-radius: 3px; }
scale.mseek slider { min-width: 13px; min-height: 13px; background: white; border: none; box-shadow: 0 1px 4px alpha(black, 0.5); margin: -4px; }
.codebox { background: #0d0f0d; border-radius: 10px; padding: 8px 10px; border: 1px solid alpha(#9be36b, 0.18);
  font-family: "JetBrainsMono Nerd Font", "Fira Code", monospace; font-size: 11px; color: #e0def4; }
.codehead { color: #9be36b; font-weight: 800; font-size: 12px; }
button.actbtn { border-radius: 12px; padding: 6px 12px; border: none; box-shadow: none; font-weight: 700;
  background: alpha(white, 0.06); color: #eee; }
button.actbtn:hover { background: alpha(white, 0.11); }
button.actbtn.on { background: alpha(#ffcf5c, 0.9); color: #111; }
button.chip { border-radius: 999px; padding: 2px 10px; border: 1px dashed alpha(white, 0.2); box-shadow: none;
  background: none; color: alpha(white, 0.75); font-size: 12px; }
button.chip:hover { background: alpha(white, 0.08); color: white; }
"""


def _hypr(*args):
    try:
        return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def toggle_window(cls, cmd):
    """Scratchpad-style toggle for an app's window: start it / hide it in special:<cls> / bring it back.
    Hiding keeps the app running (hyprclick keeps clicking and anti-AFK keeps going)."""
    import json
    try:
        clients = json.loads(_hypr("clients", "-j") or "[]")
    except ValueError:
        clients = []
    win = next((c for c in clients if c.get("class") == cls), None)
    if win is None:
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return "started"
    addr = win["address"]
    if win.get("workspace", {}).get("name", "").startswith("special:"):
        try:
            ws = json.loads(_hypr("activeworkspace", "-j") or "{}").get("id")
        except ValueError:
            ws = None
        if ws is not None:
            _hypr("dispatch", f'hl.dsp.window.move({{ workspace = "{ws}", follow = false, window = "address:{addr}" }})')
        _hypr("dispatch", f'hl.dsp.focus({{ window = "address:{addr}" }})')
        return "shown"
    _hypr("dispatch", f'hl.dsp.window.move({{ workspace = "special:{cls}", follow = false, window = "address:{addr}" }})')
    return "hidden"


def _plain(md):
    """Markdown answer -> plain text for the small answer box."""
    import re
    md = re.sub(r"```[a-z]*\n?", "", md)
    md = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), md)
    md = re.sub(r"`([^`]+)`", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    md = re.sub(r"^#+\s*", "", md, flags=re.M)
    md = re.sub(r"^\s*[-*]\s+", "• ", md, flags=re.M)
    return md


def _clock(t):
    if t is None:
        return "0:00"
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def lbl(text="", css=None, x=0.0, ell=True, chars=None):
    w = Gtk.Label(label=text, xalign=x)
    if css:
        for c in css.split():
            w.add_css_class(c)
    if ell:
        w.set_ellipsize(3)
    if chars:
        w.set_max_width_chars(chars)
    return w


def btn(text, css, cb, tip=None):
    b = Gtk.Button(label=text)
    for c in css.split():
        b.add_css_class(c)
    b.set_can_focus(False)
    b.connect("clicked", lambda *_: cb())
    if tip:
        b.set_tooltip_text(tip)
    return b


def clickable(widget, primary, secondary=None, scroll=None):
    g = Gtk.GestureClick()
    g.set_button(0)

    def released(gest, n, x, y):
        if gest.get_current_button() == 3 and secondary:
            secondary()
        elif gest.get_current_button() == 1:
            primary()
    g.connect("released", released)
    widget.add_controller(g)
    if scroll:
        sc = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        sc.connect("scroll", lambda _c, dx, dy: (scroll(-1 if dy > 0 else 1), True)[1])
        widget.add_controller(sc)
    widget.set_cursor_from_name("pointer")


class Tile:
    def __init__(self, icon, bubble, on_click, on_right=None, on_scroll=None, bar=False):
        self.box = Gtk.Box(spacing=10)
        self.box.add_css_class("tile")
        self.box.add_css_class("t-" + bubble[2:])
        self.iconstack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=200)
        self.iconstack.set_valign(Gtk.Align.CENTER)
        self.icon = lbl(icon, "ico bubble " + bubble, x=0.5, ell=False)
        self.iconstack.add_named(self.icon, "icon")
        self.art = Gtk.Image()
        self.art.set_pixel_size(38)
        self.art.add_css_class("art")
        artbox = Gtk.Box()
        artbox.add_css_class("artbox")
        artbox.set_overflow(Gtk.Overflow.HIDDEN)
        artbox.append(self.art)
        self.iconstack.add_named(artbox, "art")
        self.art_path = None
        self.box.append(self.iconstack)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        v.set_valign(Gtk.Align.CENTER)
        self.title = lbl("", "tt", chars=14)
        self.sub = lbl("", "ts", chars=18)
        v.append(self.title)
        v.append(self.sub)
        self.bar = None
        if bar:
            self.bar = Gtk.ProgressBar()
            self.bar.add_css_class("tbar")
            self.bar.set_visible(False)
            v.append(self.bar)
        self.box.append(v)
        clickable(self.box, on_click, on_right, on_scroll)

    def set_art(self, path):
        if path == self.art_path:
            return
        self.art_path = path
        if path and os.path.exists(path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                side = min(pb.get_width(), pb.get_height())  # centre square crop, then scale down
                sq = pb.new_subpixbuf((pb.get_width() - side) // 2, (pb.get_height() - side) // 2, side, side)
                sq = sq.scale_simple(76, 76, GdkPixbuf.InterpType.BILINEAR)
                self.art.set_from_paintable(Gdk.Texture.new_for_pixbuf(sq))
                self.iconstack.set_visible_child_name("art")
            except GLib.Error:
                self.iconstack.set_visible_child_name("icon")
        else:
            self.iconstack.set_visible_child_name("icon")

    def set_bar(self, frac):
        if self.bar is None:
            return
        self.bar.set_visible(frac is not None)
        if frac is not None:
            self.bar.set_fraction(max(0.0, min(1.0, frac)))

    def set(self, title, sub, icon=None):
        if self.title.get_text() != title:
            self.title.set_text(title)
        if self.sub.get_text() != sub:
            self.sub.set_text(sub)
        if icon and self.icon.get_text() != icon:
            self.icon.set_text(icon)


class Dashboard(Gtk.Box):
    def __init__(self, isl, make_pet):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.isl = isl
        self.add_css_class("panel")
        self.set_size_request(660, -1)
        self.idx = 0
        self.pulse_bars = []
        self.page = "home"
        self.code_lbl = None
        self.code_obj = None
        self.code_shown = None

        # header
        hdr = Gtk.Box(spacing=4)
        self.hdr = {}
        self.hdr["home"] = btn(I["home"], "hbtn ico on", lambda: self.show("home"), "Home")
        hdr.append(self.hdr["home"])
        hdr.append(btn(I["plus"], "hbtn ico", lambda: self.show("settings", focus_add=True), "Add an app"))
        sp = Gtk.Box(hexpand=True)
        hdr.append(sp)
        self.vol = btn(I["vol"], "hbtn ico", self.toggle_sound, "Sound")
        hdr.append(self.vol)
        if len(isl.monitors()) > 1:
            hdr.append(btn(I["monitor"], "hbtn ico", isl.next_monitor, "Move to the next monitor"))
        for page, icon, tip in (("inbox", I["bell"], "Notifications"), ("updates", I["pkg"], "Updates"),
                                ("settings", I["cog"], "Settings")):
            self.hdr[page] = btn(icon, "hbtn ico", lambda p=page: self.show(p), tip)
            hdr.append(self.hdr[page])
        hdr.append(btn(I["up"], "hbtn ico", isl.close_panel, "Close"))
        self.append(hdr)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=160)
        self.stack.set_vhomogeneous(False)
        self.stack.set_interpolate_size(True)
        self.append(self.stack)

        # home
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=10)
        main = Gtk.Box(spacing=12)
        main.add_css_class("maincard")
        main.set_size_request(300, -1)
        self.pet = make_pet(76)
        self.pet.set_valign(Gtk.Align.START)
        main.append(self.pet)
        self.mainv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        main.append(self.mainv)
        top.append(main)

        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        self.t_music = Tile(I["music"], "b-music", isl.music_toggle, isl.music_next, bar=True)
        self.t_timer = Tile(I["timer"], "b-timer", isl.timer_click, isl.timer_reset, isl.timer_adjust)
        self.t_clock = Tile(I["clock"], "b-clock", lambda: None)
        self.t_upd = Tile(I["pkg"], "b-upd", lambda: self.show("updates"))
        self.t_click = Tile(I["click"], "b-click", self.open_hyprclick)
        self.t_cog = Tile(I["cog"], "b-cog", lambda: self.show("settings"))
        for i, t in enumerate((self.t_music, self.t_timer, self.t_clock, self.t_upd, self.t_click, self.t_cog)):
            grid.attach(t.box, i % 2, i // 2, 1, 1)
        top.append(grid)
        home.append(top)
        self.btnrow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                  column_spacing=8, row_spacing=8)
        home.append(self.btnrow)
        self.acts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        home.append(self.acts)
        self.stack.add_named(home, "home")

        self.settings = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.settings.set_propagate_natural_height(True)
        self.settings.set_max_content_height(460)
        self.stack.add_named(self.settings, "settings")
        self.mediapage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.stack.add_named(self.mediapage, "media")
        self.m = None
        self.updates = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.stack.add_named(self.updates, "updates")
        self.inbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.stack.add_named(self.inbox, "inbox")
        self.update_tiles()

    # ------------------------------------------------------------------ navigation
    def show(self, page, focus_add=False):
        self.page = page
        for name, b in self.hdr.items():
            (b.add_css_class if name == page else b.remove_css_class)("on")
        if page == "settings":
            self.build_settings(focus_add)
        elif page == "updates":
            self.build_updates()
        elif page == "media":
            self.build_media()
        elif page == "inbox":
            self.build_inbox()
        else:
            self.rebuild_home()
        self.stack.set_visible_child_name(page)

    def toggle_sound(self):
        self.isl.conf["sound"] = not self.isl.conf.get("sound", True)
        save_conf(self.isl.conf)
        self.update_tiles()

    def open_hyprclick(self):
        toggle_window("hyprclick", ["hyprclick"])

    # ------------------------------------------------------------------ home
    def refresh(self):
        if self.page == "home":
            self.rebuild_home()
        elif self.page == "updates":
            self.build_updates()

    def rebuild_home(self):
        isl = self.isl
        while (c := self.mainv.get_first_child()) is not None:
            self.mainv.remove(c)
        sess = sorted((s for s in isl.sessions.values() if isl.app_on(s.src)), key=lambda s: s.updated, reverse=True)
        if isl.pending:
            s0 = isl.pending[0].sess
            if s0 in sess:
                self.idx = sess.index(s0)
        if sess:
            self.idx %= len(sess)
            s = sess[self.idx]
            row = Gtk.Box(spacing=6)
            r, g, b = COLORS[s.state]
            row.append(self._dot((r, g, b)))
            row.append(lbl(s.project, "proj", chars=16))
            row.append(lbl(s.agent, "agentlbl", chars=12))
            row.append(Gtk.Box(hexpand=True))
            if len(sess) > 1:
                row.append(btn(I["left"], "mini ico", lambda: self.page_sess(-1)))
                row.append(lbl(f"{self.idx + 1}/{len(sess)}", "agentlbl", ell=False))
                row.append(btn(I["right"], "mini ico", lambda: self.page_sess(1)))
            self.mainv.append(row)
            icon, text, col = {
                "done": (I["check"], "Done", "#9be36b"), "working": (I["dot"], "Working", "#ffa94d"),
                "question": (I["q"], "Waiting for you", "#ffd23c"), "idle": (I["dot"], "Idle", "#9a9aa6"),
            }[s.state]
            st = Gtk.Label(xalign=0)
            st.set_markup(f"<span foreground='{col}'><span font_family='Symbols Nerd Font'>{icon}</span>  {text}</span>")
            st.add_css_class("status")
            self.mainv.append(st)
            self.code_lbl = self.code_obj = self.code_shown = None
            c = s.code
            if s.state in ("working", "question") and c and time.time() - c["t0"] < 90:
                self.mainv.append(lbl(c.get("label", ""), "codehead", chars=34))
                self.code_lbl = Gtk.Label(xalign=0, yalign=0)
                self.code_lbl.add_css_class("codebox")
                self.code_lbl.set_vexpand(True)
                self.code_lbl.set_size_request(-1, 150)
                self.code_obj = c
                self.mainv.append(self.code_lbl)
                self.update_code()
                return self._rebuild_rest()
            body = _plain(s.answer.strip()) if s.state == "done" and s.answer else \
                "\n".join(f"{tm}  {_first_line(x, 44)}" for tm, x in list(s.hist)[-4:]) or s.text
            box = lbl(body[:420], "answerbox", ell=False)
            box.set_wrap(True)
            box.set_wrap_mode(2)
            box.set_lines(5)
            box.set_ellipsize(3)
            box.set_max_width_chars(34)
            box.set_vexpand(True)
            box.set_yalign(0)
            self.mainv.append(box)
        else:
            h = time.localtime().tm_hour
            hello = "Good morning" if 5 <= h < 12 else "Good afternoon" if h < 18 else "Good evening" if h < 23 else "Up late"
            self.mainv.append(lbl(f"{hello}, {model_user_name(isl.conf)} ✨", "greet", chars=22))
            self.mainv.append(lbl(f"{isl.pet_name()} is {pip.MOODS[isl.mood()].lower()}", "agentlbl"))
            chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                column_spacing=6, row_spacing=6)
            np = isl.now_playing()
            if np:
                chips.append(lbl(np[0], "chip hot", chars=30))
            if isl.updates.total:
                chips.append(lbl(f"{I['pkg']}  {isl.updates.total} updates", "chip ico", ell=False))
            n_acts = len([a for a in isl.live_acts() if not a.get("toast")])
            if n_acts:
                chips.append(lbl(f"{n_acts} live", "chip", ell=False))
            if isl.timer_end:
                chips.append(lbl(f"{I['timer']}  {isl.timer_text()}", "chip ico", ell=False))
            if chips.get_first_child():
                self.mainv.append(chips)
            hint = lbl("Claude Code, Codex, Steam, downloads and hyprclick show up here when they're busy.",
                       "hint", ell=False)
            hint.set_wrap(True)
            hint.set_max_width_chars(34)
            hint.set_vexpand(True)
            hint.set_valign(Gtk.Align.END)
            self.mainv.append(hint)
        self._rebuild_rest()

    def _rebuild_rest(self):
        isl = self.isl
        while (c := self.btnrow.get_first_child()) is not None:
            self.btnrow.remove(c)
        if isl.app_on("actions"):
            for a in isl.conf.get("actions", []):
                on = isl.runner.running(a["name"])
                b = btn(f"{I['pause'] if on else I['play']}  {a['name']}", "actbtn" + (" on" if on else ""),
                        lambda a=a: isl.run_action(a), "Click again to stop" if on else a["cmd"])
                self.btnrow.append(b)
        self.btnrow.set_visible(self.btnrow.get_first_child() is not None)
        while (c := self.acts.get_first_child()) is not None:
            self.acts.remove(c)
        self.pulse_bars = []
        for a in isl.live_acts():
            if not a.get("toast"):  # toasts live in the 🔔 page
                self.acts.append(self._act_card(a))

    def update_code(self):
        if not self.code_lbl or not self.code_obj:
            return
        c = self.code_obj
        chars = int((time.time() - c["t0"]) * 140) + 12
        total = sum(len(x) + 1 for x in c["added"])
        key = min(chars, total + 1)
        if key == self.code_shown:
            return
        self.code_shown = key
        markup = highlight.render(c, chars)
        if chars <= total:
            markup += "<span foreground='#9be36b'>▍</span>"
        self.code_lbl.set_markup(markup or "<span foreground='#6e6a86'>(empty)</span>")

    def _dot(self, rgb):
        w = Gtk.Label()
        r, g, b = rgb
        w.set_markup(f"<span foreground='#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'>●</span>")
        return w

    def page_sess(self, d):
        self.idx += d
        self.rebuild_home()

    def _act_card(self, a):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("actcard")
        top = Gtk.Box(spacing=8)
        icon = {"steam": I["steam"], "downloads": I["dl"], "hyprclick": I["click"], "timer": I["timer"],
                "updates": I["pkg"]}.get(a["app"], I["dot"])
        il = Gtk.Label()
        il.set_markup(f"<span foreground='{a.get('color', '#9a9aa6')}' font_family='Symbols Nerd Font'>{icon}</span>")
        top.append(il)
        top.append(lbl(a["title"], "tt", chars=26))
        top.append(lbl(a.get("detail", ""), "ts", chars=44, x=0))
        top.append(Gtk.Box(hexpand=True))
        top.append(lbl(SOURCES.get(a["app"], a["app"]), "agentlbl", ell=False))
        card.append(top)
        if a.get("lines") and a["app"] == "actions":
            out = lbl("\n".join(highlight.escape(x[:90]) for x in a["lines"][-3:]), "mono", ell=False)
            out.set_use_markup(True)
            card.append(out)
        frac = a.get("progress")
        if frac is None and a.get("total") and a.get("until"):
            frac = max(0.0, min(1.0, (a["until"] - time.time()) / a["total"]))
        if frac is not None or a.get("pulse"):
            bar = Gtk.ProgressBar()
            bar.add_css_class("bar")
            if frac is not None:
                bar.set_fraction(frac)
            else:
                bar.set_pulse_step(0.08)
                self.pulse_bars.append(bar)
            card.append(bar)
        return card

    def update_tiles(self):
        isl = self.isl
        m = isl.music
        if m.get("title"):
            self.t_music.set(m["title"], m.get("artist") or m.get("player", ""),
                             I["pause"] if m.get("status") == "Playing" else I["play"])
            art = m.get("art", "")
            self.t_music.set_art(art[7:] if art.startswith("file://") else None)
            ln, pos = m.get("length"), m.get("pos")
            self.t_music.set_bar(pos / ln if ln and pos is not None else None)
        else:
            self.t_music.set("Music", "Nothing playing", I["music"])
            self.t_music.set_art(None)
            self.t_music.set_bar(None)
        self.t_timer.set(isl.timer_text(), isl.timer_sub())
        self.t_clock.set(time.strftime("%H:%M"), time.strftime("%a %d %b"))
        u = isl.updates
        if u.running:
            self.t_upd.set("Updating…", "in the terminal")
        elif u.checking and not u.checked:
            self.t_upd.set("Checking…", "pacman · AUR · Flatpak")
        elif u.checked:
            n = u.total
            self.t_upd.set(f"{n} update{'s' if n != 1 else ''}" if n else "Up to date",
                           u.summary() if n else time.strftime("checked %H:%M", time.localtime(u.checked)))
        else:
            self.t_upd.set("Updates", "not checked yet")
        hc = [a for a in isl.live_acts() if a["app"] == "hyprclick" and not a.get("flash")]
        if hc:
            self.t_click.set(hc[0]["title"], hc[0].get("detail", ""))
        else:
            self.t_click.set("hyprclick", "Idle · click to open")
        self.t_cog.set("Settings", "Sources, updates")
        snd = isl.conf.get("sound", True)
        self.vol.set_label(I["vol"] if snd else I["mute"])
        for b in self.pulse_bars:
            b.pulse()
        self.update_code()
        if self.page == "media":
            self.update_media()

    # ------------------------------------------------------------------ now playing page
    def build_media(self):
        box = self.mediapage
        while (c := box.get_first_child()) is not None:
            box.remove(c)
        m = self.m = {}
        row = Gtk.Box(spacing=16)
        artbox = Gtk.Box()
        artbox.add_css_class("bigart")
        artbox.set_overflow(Gtk.Overflow.HIDDEN)
        artbox.set_valign(Gtk.Align.START)
        artbox.set_halign(Gtk.Align.START)
        artbox.set_hexpand(False)
        artbox.set_size_request(320, 180)
        m["art"] = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER)
        m["art"].set_size_request(320, 180)
        m["art_path"] = None
        artbox.append(m["art"])
        row.append(artbox)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        m["where"] = lbl("", "chip hot", ell=False)
        m["where"].set_halign(Gtk.Align.START)
        v.append(m["where"])
        m["title"] = lbl("", "mtitle", ell=False)
        m["title"].set_wrap(True)
        m["title"].set_lines(2)
        m["title"].set_ellipsize(3)
        m["title"].set_max_width_chars(30)
        v.append(m["title"])
        m["artist"] = lbl("", "ts", chars=36)
        v.append(m["artist"])
        v.append(Gtk.Box(vexpand=True))
        m["seek"] = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        m["seek"].set_draw_value(False)
        m["seek"].add_css_class("mseek")
        m["seek"].connect("change-value", lambda _s, _sc, val: (self.isl.media("seek", val), False)[1])
        v.append(m["seek"])
        times = Gtk.Box()
        m["pos"] = lbl("0:00", "mono", ell=False)
        m["len"] = lbl("0:00", "mono", ell=False)
        times.append(m["pos"])
        times.append(Gtk.Box(hexpand=True))
        times.append(m["len"])
        v.append(times)
        ctl = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        m["prev"] = btn(I["prev"], "mctl ico", lambda: self.isl.media("previous"), "Previous")
        ctl.append(m["prev"])
        ctl.append(btn(I["rew"], "mctl ico", lambda: self.isl.media("back"), "Back 10 s"))
        m["pp"] = btn(I["pause"], "mctl ico big", lambda: self.isl.media("toggle"), "Play / pause")
        ctl.append(m["pp"])
        ctl.append(btn(I["ffw"], "mctl ico", lambda: self.isl.media("fwd"), "Forward 10 s"))
        m["next"] = btn(I["next"], "mctl ico", lambda: self.isl.media("next"), "Next")
        ctl.append(m["next"])
        v.append(ctl)
        row.append(v)
        box.append(row)

        bottom = Gtk.Box(spacing=10)
        bottom.append(lbl(I["vol"], "ico ts", ell=False))
        m["vol"] = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.02)
        m["vol"].set_draw_value(False)
        m["vol"].set_size_request(150, -1)
        m["vol"].add_css_class("mseek")
        m["vol"].connect("change-value", lambda _s, _sc, val: (self.isl.media("volume", max(0.0, min(1.0, val))), False)[1])
        bottom.append(m["vol"])
        bottom.append(Gtk.Box(hexpand=True))
        m["browser"] = btn(f"{I['web']}  Back to browser", "act", lambda: self.isl.media("browser"))
        m["close"] = btn(f"{I['close']}  Close mini player", "act", lambda: self.isl.media("close"))
        m["pop"] = btn(f"{I['popout']}  Pop out", "act primary", self.isl.pop_out, "Play it in a small window on top of everything")
        for k in ("browser", "close", "pop"):
            bottom.append(m[k])
        box.append(bottom)
        self.update_media(force=True)

    def update_media(self, force=False):
        m, isl = self.m, self.isl
        if not m:
            return
        mu = isl.music
        pos, length, playing, vol, where = isl.media_state()
        title = mu.get("title") or "Nothing playing"
        if m["title"].get_text() != title:
            m["title"].set_text(title)
        m["artist"].set_text(mu.get("artist") or "")
        mini = where == "mini"
        app = mu.get("player", "").split(".")[0]
        m["where"].set_text("In the mini player" if mini else "Browser" if app in isl.BROWSERS else (app.capitalize() or "—"))
        art = mu.get("art", "")
        path = art[7:] if art.startswith("file://") else None
        if path != m["art_path"]:
            m["art_path"] = path
            if path and os.path.exists(path):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(path)
                    w, h = pb.get_width(), pb.get_height()
                    cw, ch = (w, w * 9 // 16) if w * 9 // 16 <= h else (h * 16 // 9, h)
                    cw, ch = int(cw * 0.94), int(ch * 0.94)  # trim the edges: many thumbnails have a border
                    pb = pb.new_subpixbuf((w - cw) // 2, (h - ch) // 2, cw, ch).scale_simple(320, 180, GdkPixbuf.InterpType.BILINEAR)
                    m["art"].set_paintable(Gdk.Texture.new_for_pixbuf(pb))
                except GLib.Error:
                    m["art"].set_paintable(None)
            else:
                m["art"].set_paintable(None)
        if length:
            m["seek"].set_range(0, length)
            if pos is not None:
                m["seek"].set_value(pos)
        m["seek"].set_sensitive(bool(length))
        m["pos"].set_text(_clock(pos))
        m["len"].set_text(_clock(length))
        m["pp"].set_label(I["pause"] if playing else I["play"])
        if vol is not None:
            m["vol"].set_value(vol)
        m["prev"].set_sensitive(not mini)
        m["next"].set_sensitive(not mini)
        m["browser"].set_visible(mini)
        m["close"].set_visible(mini)
        m["pop"].set_visible(not mini and bool(mu.get("player", "").split(".")[0] in isl.BROWSERS))

    # ------------------------------------------------------------------ notifications page
    def build_inbox(self):
        box = self.inbox
        while (c := box.get_first_child()) is not None:
            box.remove(c)
        head = Gtk.Box(spacing=8)
        head.append(lbl("Notifications", "pagetitle"))
        head.append(Gtk.Box(hexpand=True))
        head.append(btn("Clear", "act", self.clear_inbox))
        box.append(head)
        if not self.isl.inbox:
            box.append(lbl("Nothing yet. Islet's alerts land here instead of system popups.", "empty"))
            return
        for n in list(self.isl.inbox)[:12]:
            row = Gtk.Box(spacing=10)
            row.add_css_class("actcard")
            col = n.get("color") or ("#9be36b" if n["kind"] == "done" else "#ffd23c")
            ic = Gtk.Label()
            ic.set_markup(f"<span foreground='{col}' font_family='Symbols Nerd Font'>{I['check'] if n['kind'] == 'done' else I['bell']}</span>")
            row.append(ic)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
            v.append(lbl(n["title"], "tt", chars=50))
            if n["body"]:
                v.append(lbl(n["body"], "ts", chars=70))
            row.append(v)
            row.append(lbl(time.strftime("%H:%M", time.localtime(n["t"])), "agentlbl", ell=False))
            box.append(row)

    def clear_inbox(self):
        self.isl.inbox.clear()
        self.build_inbox()

    # ------------------------------------------------------------------ updates page
    def build_updates(self):
        u = self.isl.updates
        box = self.updates
        while (c := box.get_first_child()) is not None:
            box.remove(c)
        head = Gtk.Box(spacing=8)
        head.append(lbl("Updates", "pagetitle"))
        head.append(lbl("checking…" if u.checking else (time.strftime("checked %H:%M", time.localtime(u.checked)) if u.checked else ""), "hint"))
        head.append(Gtk.Box(hexpand=True))
        head.append(btn(f"{I['refresh']}  Check now", "act", u.check))
        box.append(head)
        cols = Gtk.Box(spacing=10, homogeneous=True)
        for name, items in (("Arch", u.repo), ("AUR", u.aur), ("Flatpak", u.flatpak)):
            c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            c.add_css_class("srow")
            c.append(lbl(f"{name} · {len(items)}", "tt"))
            text = "\n".join(_first_line(x, 40) for x in items[:14]) + (f"\n… {len(items) - 14} more" if len(items) > 14 else "")
            t = lbl(text or "nothing to update", "mono", ell=False)
            t.set_yalign(0)
            c.append(t)
            cols.append(c)
        box.append(cols)
        acts = Gtk.Box(spacing=8)
        acts.append(btn(f"{I['term']}  Update everything", "act primary", lambda: self.isl.run_update(0)))
        acts.append(btn("Flatpak only (silent)", "act", lambda: self.isl.run_update(1)))
        box.append(acts)
        box.append(lbl("Arch and AUR updates open in your terminal, since pacman needs your password.", "hint", ell=False))
        if self.isl.conf.get("upd_skip"):
            box.append(lbl(f"Skipping: {self.isl.conf['upd_skip']}  (Settings → Updates)", "hint", ell=False))

    # ------------------------------------------------------------------ settings page
    def build_settings(self, focus_add=False):
        isl, conf = self.isl, self.isl.conf
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        v.set_margin_end(6)
        v.append(lbl("Settings", "pagetitle"))

        def section(t):
            v.append(lbl(t, "section"))

        def switch_row(text, active, cb, extra=None):
            row = Gtk.Box(spacing=8)
            row.add_css_class("srow")
            row.append(lbl(text, "tt", chars=30))
            row.append(Gtk.Box(hexpand=True))
            if extra:
                row.append(extra)
            sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _p: cb(s.get_active()))
            row.append(sw)
            v.append(row)

        def set_app(app, on):
            conf.setdefault("apps", {})[app] = on
            save_conf(conf)
            isl.refresh()

        section("SHOW IN THE ISLAND")
        for app, name in SOURCES.items():
            switch_row(name, isl.app_on(app), lambda on, a=app: set_app(a, on))
        for c in conf.get("custom", []):
            rm = btn(I["close"], "mini ico", lambda n=c["name"]: self.remove_custom(n), "Remove")
            switch_row(f"{c['name']}  ·  {_first_line(c['cmd'], 28)}", isl.app_on(c["name"]),
                       lambda on, a=c["name"]: set_app(a, on), rm)

        section("SCRIPT BUTTONS")
        have = {a["cmd"] for a in conf.get("actions", [])}
        for a in conf.get("actions", []):
            row = Gtk.Box(spacing=8)
            row.add_css_class("srow")
            row.append(lbl(f"{I['play']}", "ico", ell=False))
            row.append(lbl(a["name"], "tt", chars=18))
            row.append(lbl(a["cmd"], "ts", chars=36))
            row.append(Gtk.Box(hexpand=True))
            row.append(btn(I["close"], "mini ico", lambda n=a["name"]: self.remove_action(n), "Remove"))
            v.append(row)
        found = [p for p in acts_mod.find_scripts() if p not in have][:14]
        if found:
            v.append(lbl("Found in your bin folders: click one to add it", "hint"))
            fl = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=6, row_spacing=6)
            for p in found:
                fl.append(btn(os.path.basename(p), "chip", lambda p=p: self.add_action(acts_mod.nice_name(p), p), p))
            v.append(fl)
        add2 = Gtk.Box(spacing=6)
        aname = Gtk.Entry(placeholder_text="Name", width_chars=10)
        acmd = Gtk.Entry(placeholder_text="Script or command, e.g. vr-up", hexpand=True)
        add2.append(aname)
        add2.append(acmd)
        add2.append(btn("Choose file…", "act", lambda: self.pick_file(aname, acmd)))
        add2.append(btn("Add", "act primary", lambda: self.add_action(aname.get_text() or acts_mod.nice_name(acmd.get_text()), acmd.get_text())))
        v.append(add2)

        section("ADVANCED: LIVE STATUS FROM A COMMAND")
        add = Gtk.Box(spacing=6)
        name = Gtk.Entry(placeholder_text="Name", width_chars=10)
        cmd = Gtk.Entry(placeholder_text="Command, e.g. cat ~/progress.txt", hexpand=True)
        every = Gtk.SpinButton.new_with_range(1, 3600, 1)
        every.set_value(2)
        every.set_tooltip_text("Run every N seconds")
        add.append(name)
        add.append(cmd)
        add.append(every)
        add.append(btn("Add", "act primary", lambda: self.add_custom(name.get_text(), cmd.get_text(), every.get_value())))
        v.append(add)
        v.append(lbl("Its first line of output is shown; no output hides it. Start the line with 42% for a "
                     "progress bar. Scripts can also use: islet push --app NAME --title TEXT", "hint", ell=False))
        v.get_last_child().set_wrap(True)

        section("UPDATES")
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Check for updates every", "tt"))
        row.append(Gtk.Box(hexpand=True))
        dd = Gtk.DropDown.new_from_strings([f"{h} h" for h in upd.EVERY_H])
        dd.set_selected(upd.EVERY_H.index(conf.get("upd_every_h", 3)) if conf.get("upd_every_h", 3) in upd.EVERY_H else 1)
        dd.connect("notify::selected", lambda d, _p: self._set("upd_every_h", upd.EVERY_H[d.get_selected()]))
        row.append(dd)
        v.append(row)

        tm = Gtk.Box(spacing=4)
        hh = Gtk.SpinButton.new_with_range(0, 23, 1)
        hh.set_value(conf.get("auto_hour", 20))
        mm = Gtk.SpinButton.new_with_range(0, 59, 5)
        mm.set_value(conf.get("auto_min", 0))
        hh.connect("value-changed", lambda s: self._set("auto_hour", int(s.get_value())))
        mm.connect("value-changed", lambda s: self._set("auto_min", int(s.get_value())))
        tm.append(hh)
        tm.append(lbl(":", "tt", ell=False))
        tm.append(mm)
        switch_row("Update every day at", conf.get("auto_update", False), lambda on: self._set("auto_update", on), tm)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Daily update does", "tt"))
        row.append(Gtk.Box(hexpand=True))
        md = Gtk.DropDown.new_from_strings(upd.AUTO_MODES)
        md.set_selected(conf.get("auto_mode", 0))
        md.connect("notify::selected", lambda d, _p: self._set("auto_mode", d.get_selected()))
        row.append(md)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Skip packages", "tt"))
        row.append(Gtk.Box(hexpand=True))
        se = Gtk.Entry(placeholder_text="e.g. rootapp-bin", width_chars=24)
        se.set_text(conf.get("upd_skip", ""))
        se.set_tooltip_text("Left out of updates (yay/pacman --ignore). Handy when one AUR package is broken.")
        se.connect("changed", lambda e: self._set("upd_skip", e.get_text().strip()))
        row.append(se)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Terminal", "tt"))
        row.append(Gtk.Box(hexpand=True))
        te = Gtk.Entry(placeholder_text=next((t for t in upd.TERMINALS if shutil.which(t)), "kitty"), width_chars=12)
        te.set_text(conf.get("terminal", ""))
        te.connect("changed", lambda e: self._set("terminal", e.get_text().strip()))
        row.append(te)
        v.append(row)

        section("VIDEOS")
        import ytproxy
        browsers = ytproxy.find_browsers()
        switch_row("Use my YouTube login in the mini player", conf.get("yt_login", False),
                   lambda on: self._set_login(on, browsers))
        if browsers:
            row = Gtk.Box(spacing=8)
            row.add_css_class("srow")
            row.append(lbl("Login from", "tt"))
            row.append(Gtk.Box(hexpand=True))
            bd = Gtk.DropDown.new_from_strings([b[0] for b in browsers])
            specs = [b[1] for b in browsers]
            if conf.get("yt_cookies") in specs:
                bd.set_selected(specs.index(conf["yt_cookies"]))
            bd.connect("notify::selected", lambda d, _p: self._set("yt_cookies", specs[d.get_selected()]))
            row.append(bd)
            row.append(btn("Sign in to YouTube", "act", lambda: subprocess.Popen(
                ["xdg-open", "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
            v.append(row)
        h = lbl("Most videos play without it. Age-restricted and members-only videos, or YouTube's "
                "\"not a bot\" check, need you signed in. The login is read from your browser on this PC "
                "and only sent to YouTube.", "hint", ell=False)
        h.set_wrap(True)
        v.append(h)

        section("ALERTS")
        switch_row("Sound when done or asking", conf.get("sound", True), lambda on: self._set("sound", on))
        switch_row("Welcome me when I log in", conf.get("welcome", True), lambda on: self._set("welcome", on))
        switch_row("Also send system popups (Noctalia etc.)", conf.get("desktop_notify", False),
                   lambda on: self._set("desktop_notify", on))

        section("LOOK")
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Pet", "tt"))
        row.append(Gtk.Box(hexpand=True))
        for sp, nm in pip.PETS.items():
            b = btn(("🐶 " if sp == "pup" else "🐱 ") + isl.pet_name(sp), "pet" + (" on" if conf["pet"] == sp else ""),
                    lambda s=sp: (isl.set_pet(s), self.build_settings()))
            row.append(b)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Your name", "tt"))
        row.append(Gtk.Box(hexpand=True))
        ue = Gtk.Entry(width_chars=12, placeholder_text=model_user_name(conf))
        ue.set_text(conf.get("user_name", ""))
        ue.connect("changed", lambda e: self._set("user_name", e.get_text().strip()))
        row.append(ue)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Pet's name", "tt"))
        row.append(Gtk.Box(hexpand=True))
        ne = Gtk.Entry(width_chars=12)
        ne.set_text(isl.pet_name())
        ne.connect("changed", lambda e: self._rename_pet(e.get_text()))
        row.append(ne)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Accent colour", "tt"))
        row.append(Gtk.Box(hexpand=True))
        for col in ACCENTS:
            b = btn("", "swatch" + (" on" if conf.get("accent") == col else ""), lambda c=col: self.set_accent(c))
            prov = Gtk.CssProvider()
            prov.load_from_string(f"button {{ background: {col}; }}")
            b.get_style_context().add_provider(prov, 900)
            row.append(b)
        v.append(row)
        row = Gtk.Box(spacing=8)
        row.add_css_class("srow")
        row.append(lbl("Position", "tt"))
        row.append(Gtk.Box(hexpand=True))
        row.append(btn("Back to top middle", "act", isl.reset_position))
        v.append(row)
        mons = [m.get_connector() for m in isl.monitors()]
        if len(mons) > 1:
            row = Gtk.Box(spacing=8)
            row.add_css_class("srow")
            row.append(lbl("Show on", "tt"))
            row.append(Gtk.Box(hexpand=True))
            cur = isl.current_monitor_name()
            for i, name in enumerate(mons, 1):
                row.append(btn(f"Monitor {i} · {name}", "pet" + (" on" if name == cur else ""),
                               lambda n=name: (isl.move_to_monitor(n), GLib.timeout_add(300, lambda: (self.build_settings(), False)[1]))))
        v.append(row)

        self.settings.set_child(v)
        if focus_add:
            acmd.grab_focus()

    def _set(self, key, val):
        self.isl.conf[key] = val
        save_conf(self.isl.conf)
        self.isl.refresh()

    def _set_login(self, on, browsers):
        if on and not self.isl.conf.get("yt_cookies") and browsers:
            self.isl.conf["yt_cookies"] = browsers[0][1]
        self._set("yt_login", on)

    def _rename_pet(self, name):
        names = dict(self.isl.conf.get("pet_names") or {})
        names[self.isl.conf.get("pet", "pup")] = name.strip() or None
        self._set("pet_names", {k: v for k, v in names.items() if v})

    def set_accent(self, col):
        self._set("accent", col)
        self.build_settings()

    def add_custom(self, name, cmd, every):
        name, cmd = name.strip(), cmd.strip()
        if not name or not cmd:
            return
        cs = [c for c in self.isl.conf.get("custom", []) if c["name"] != name]
        cs.append({"name": name, "cmd": cmd, "every": every})
        self._set("custom", cs)
        self.build_settings()

    def add_action(self, name, cmd):
        name, cmd = name.strip(), cmd.strip()
        if not cmd:
            return
        name = name or acts_mod.nice_name(cmd)
        acts = [a for a in self.isl.conf.get("actions", []) if a["name"] != name]
        acts.append({"name": name, "cmd": cmd})
        self._set("actions", acts)
        self.build_settings()

    def remove_action(self, name):
        self._set("actions", [a for a in self.isl.conf.get("actions", []) if a["name"] != name])
        self.build_settings()

    def pick_file(self, name_entry, cmd_entry):
        dlg = Gtk.FileDialog(title="Choose a script", initial_folder=Gio.File.new_for_path(os.path.expanduser("~/.local/bin")))

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            path = f.get_path()
            cmd_entry.set_text(path)
            if not name_entry.get_text():
                name_entry.set_text(acts_mod.nice_name(path))
        dlg.open(self.get_root(), None, done)

    def remove_custom(self, name):
        self._set("custom", [c for c in self.isl.conf.get("custom", []) if c["name"] != name])
        self.build_settings()
