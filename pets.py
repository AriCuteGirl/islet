"""Islet pets: Pip the pup and Mochi the kitty. Pure cairo drawing, no GTK, so it can also render PNGs."""
import math

MOODS = {
    "sleepy": "Sleepy",
    "focus": "Focused",
    "curious": "Curious",
    "happy": "Happy",
    "wink": "Wink",
    "love": "In love",
    "dizzy": "Dizzy",
}

FUR = (0.965, 0.918, 0.847)
FUR_EDGE = (0.86, 0.78, 0.67)
EAR = (0.42, 0.29, 0.23)
EAR_EDGE = (0.30, 0.20, 0.16)
EAR_IN = (0.55, 0.40, 0.32)
MUZZLE = (1.0, 0.97, 0.93)
INK = (0.13, 0.09, 0.08)
BLUSH = (1.0, 0.55, 0.62)
TONGUE = (0.97, 0.45, 0.52)

PETS = {"pup": "Pip", "kitty": "Mochi"}
CAT_FUR = (0.83, 0.81, 0.88)
CAT_EDGE = (0.66, 0.63, 0.72)
CAT_STRIPE = (0.52, 0.48, 0.58)
CAT_EAR_IN = (1.0, 0.72, 0.78)
CAT_NOSE = (0.95, 0.5, 0.6)


def _cat_ear(cr, side, angle):
    cr.save()
    cr.translate(50 + side * 22, 34)
    cr.rotate(side * angle)
    cr.move_to(side * -12, 4)
    cr.line_to(side * 4, -26)
    cr.line_to(side * 14, 2)
    cr.close_path()
    cr.set_source_rgb(*CAT_FUR)
    cr.fill_preserve()
    cr.set_line_width(1.6)
    cr.set_source_rgb(*CAT_EDGE)
    cr.stroke()
    cr.move_to(side * -6, 0)
    cr.line_to(side * 3.5, -18)
    cr.line_to(side * 9, 0)
    cr.close_path()
    cr.set_source_rgb(*CAT_EAR_IN)
    cr.fill()
    cr.restore()


def _ellipse(cr, x, y, rx, ry):
    cr.save()
    cr.translate(x, y)
    cr.scale(max(rx, 0.01), max(ry, 0.01))
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()


def _heart(cr, x, y, s):
    cr.move_to(x, y + s * 0.9)
    cr.curve_to(x - s * 1.4, y, x - s * 0.7, y - s * 1.0, x, y - s * 0.35)
    cr.curve_to(x + s * 0.7, y - s * 1.0, x + s * 1.4, y, x, y + s * 0.9)
    cr.close_path()


def _ear(cr, side, angle):
    """Floppy pup ear hanging over the side of the head, pivoting at its root."""
    cr.save()
    cr.translate(50 + side * 21, 28)
    cr.rotate(side * angle)
    cr.scale(side, 1)

    def shape(k):
        cr.move_to(-5 * k, 1 * k)
        cr.curve_to(2 * k, -5 * k, 14 * k, -5 * k, 19 * k, 3 * k)
        cr.curve_to(25 * k, 12 * k, 25 * k, 30 * k, 20 * k, 40 * k)
        cr.curve_to(17 * k, 47 * k, 8 * k, 48 * k, 5 * k, 41 * k)
        cr.curve_to(2 * k, 32 * k, 0 * k, 16 * k, -5 * k, 1 * k)
        cr.close_path()

    shape(1.0)
    cr.set_source_rgb(*EAR)
    cr.fill_preserve()
    cr.set_line_width(1.4)
    cr.set_source_rgb(*EAR_EDGE)
    cr.stroke()
    cr.save()
    cr.translate(6, 8)
    shape(0.62)
    cr.set_source_rgb(*EAR_IN)
    cr.fill()
    cr.restore()
    cr.restore()


def draw(cr, w, h, mood="focus", t=0.0, blink=0.0, accent=(1.0, 0.6, 0.24), glow=0.0, species="pup"):
    """Draw the pet into a w x h box. blink: 0 open .. 1 closed."""
    cat = species == "kitty"
    s = min(w, h) / 100.0
    cr.save()
    cr.translate((w - 100 * s) / 2, (h - 100 * s) / 2)
    cr.scale(s, s)

    if glow > 0:
        import cairo
        g = cairo.RadialGradient(50, 56, 4, 50, 56, 52)
        g.add_color_stop_rgba(0, *accent, 0.55 * glow)
        g.add_color_stop_rgba(1, *accent, 0)
        cr.set_source(g)
        cr.rectangle(0, 0, 100, 100)
        cr.fill()

    bob, tilt, ear_l, ear_r = 0.0, 0.0, 0.0, 0.0
    if mood == "happy":
        bob = -abs(math.sin(t * 6)) * 6
        ear_l = ear_r = 0.25 + math.sin(t * 12) * 0.2
    elif mood == "focus":
        bob = math.sin(t * 2.2) * 1.2
    elif mood == "sleepy":
        bob = math.sin(t * 1.2) * 1.5 + 2
        ear_l = ear_r = -0.05
    elif mood == "curious":
        tilt = 0.16 + math.sin(t * 2) * 0.04
        ear_l, ear_r = -0.55, 0.1
    elif mood == "dizzy":
        tilt = math.sin(t * 7) * 0.18
        ear_l, ear_r = math.sin(t * 9) * 0.4, -math.sin(t * 9) * 0.4
    elif mood == "love":
        bob = math.sin(t * 4) * 2
        ear_l = ear_r = 0.15
    elif mood == "wink":
        tilt = -0.08

    cr.save()
    cr.translate(50, 56 + bob)
    cr.rotate(tilt)
    cr.translate(-50, -56)

    if cat:
        # collar with a bell in the state colour
        cr.move_to(27, 74)
        cr.curve_to(40, 86, 60, 86, 73, 74)
        cr.set_line_width(5)
        cr.set_source_rgb(*accent)
        cr.stroke()
        _ellipse(cr, 50, 86, 5, 5)
        cr.set_source_rgb(1.0, 0.84, 0.35)
        cr.fill()
        _cat_ear(cr, -1, ear_l * 0.6)
        _cat_ear(cr, 1, ear_r * 0.6)
        _ellipse(cr, 50, 54, 33, 28)
        cr.set_source_rgb(*CAT_FUR)
        cr.fill_preserve()
        cr.set_line_width(1.6)
        cr.set_source_rgb(*CAT_EDGE)
        cr.stroke()
        # tabby stripes
        cr.set_source_rgb(*CAT_STRIPE)
        cr.set_line_width(2.2)
        cr.set_line_cap(1)
        for dx, ln in ((-6, 6), (0, 8), (6, 6)):
            cr.move_to(50 + dx, 28)
            cr.line_to(50 + dx * 0.8, 28 + ln)
            cr.stroke()
        _ellipse(cr, 50, 65, 11, 7.5)
        cr.set_source_rgb(*MUZZLE)
        cr.fill()
    else:
        # bandana in the state colour
        cr.move_to(30, 76)
        cr.curve_to(40, 84, 60, 84, 70, 76)
        cr.line_to(50, 96)
        cr.close_path()
        cr.set_source_rgb(*accent)
        cr.fill()
        _ellipse(cr, 50, 53, 33, 29)
        cr.set_source_rgb(*FUR)
        cr.fill_preserve()
        cr.set_line_width(1.6)
        cr.set_source_rgb(*FUR_EDGE)
        cr.stroke()
        _ear(cr, -1, ear_l)
        _ear(cr, 1, ear_r)
        _ellipse(cr, 50, 30, 7, 4)
        cr.set_source_rgba(*EAR, 0.35)
        cr.fill()
        _ellipse(cr, 50, 66, 14, 10)
        cr.set_source_rgb(*MUZZLE)
        cr.fill()

    if mood in ("happy", "love", "curious", "wink"):
        for x in (28, 72):
            _ellipse(cr, x, 63, 5.5, 3.2)
            cr.set_source_rgba(*BLUSH, 0.55)
            cr.fill()

    _eyes(cr, mood, t, blink)

    if cat:
        cr.move_to(46.5, 59.5)
        cr.line_to(53.5, 59.5)
        cr.line_to(50, 63)
        cr.close_path()
        cr.set_source_rgb(*CAT_NOSE)
        cr.fill()
        # whiskers
        cr.set_source_rgba(*CAT_EDGE, 0.9)
        cr.set_line_width(1.1)
        for side in (-1, 1):
            for dy, ang in ((-2, -0.12), (1.5, 0.0), (5, 0.14)):
                cr.move_to(50 + side * 12, 64 + dy)
                cr.line_to(50 + side * 30, 64 + dy + ang * 30 + side * 0)
                cr.stroke()
    else:
        cr.move_to(45, 60)
        cr.curve_to(46, 57.5, 54, 57.5, 55, 60)
        cr.curve_to(54, 64, 51, 65, 50, 65)
        cr.curve_to(49, 65, 46, 64, 45, 60)
        cr.close_path()
        cr.set_source_rgb(*INK)
        cr.fill()
        _ellipse(cr, 48, 59.6, 1.6, 0.9)
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.fill()

    # mouth
    cr.set_source_rgb(*INK)
    cr.set_line_width(1.6)
    cr.set_line_cap(1)
    if mood in ("happy", "love"):
        cr.move_to(43, 68)
        cr.curve_to(45, 76, 55, 76, 57, 68)
        cr.close_path()
        cr.fill()
        _ellipse(cr, 50, 73, 4, 2.6)
        cr.set_source_rgb(*TONGUE)
        cr.fill()
    elif mood == "dizzy":
        cr.move_to(44, 71)
        for i in range(1, 7):
            cr.line_to(44 + i * 2, 71 + (1.5 if i % 2 else -0.5))
        cr.stroke()
    elif mood == "curious":
        _ellipse(cr, 50, 71, 2.2, 2.6)
        cr.stroke()
    elif cat:
        cr.move_to(44, 65.5)
        cr.curve_to(45, 69, 49, 69, 50, 65.5)
        cr.curve_to(51, 69, 55, 69, 56, 65.5)
        cr.stroke()
    else:
        cr.move_to(50, 65)
        cr.line_to(50, 68)
        cr.curve_to(48, 71, 45, 71, 44, 69)
        cr.move_to(50, 68)
        cr.curve_to(52, 71, 55, 71, 56, 69)
        cr.stroke()

    cr.restore()  # undo bob/tilt
    _extras(cr, mood, t, accent)
    cr.restore()


def _open_eye(cr, x, y, r, ry, blink, look=0.0):
    ry = ry * (1 - 0.92 * blink)
    _ellipse(cr, x + look, y, r, ry)
    cr.set_source_rgb(*INK)
    cr.fill()
    if blink < 0.6:
        _ellipse(cr, x + look + r * 0.35, y - ry * 0.4, r * 0.32, r * 0.32)
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.fill()


def _eyes(cr, mood, t, blink):
    L, R, Y = 37, 63, 49
    cr.set_line_width(2.4)
    cr.set_line_cap(1)
    if mood == "sleepy":
        cr.set_source_rgb(*INK)
        for x in (L, R):
            cr.move_to(x - 5, Y)
            cr.curve_to(x - 3, Y + 4, x + 3, Y + 4, x + 5, Y)
            cr.stroke()
    elif mood == "happy":
        cr.set_source_rgb(*INK)
        for x in (L, R):
            cr.move_to(x - 5, Y + 2)
            cr.curve_to(x - 3, Y - 4, x + 3, Y - 4, x + 5, Y + 2)
            cr.stroke()
    elif mood == "focus":
        look = math.sin(t * 1.4) * 2.2
        _open_eye(cr, L, Y, 4.2, 3.6, blink, look)
        _open_eye(cr, R, Y, 4.2, 3.6, blink, look)
    elif mood == "curious":
        _open_eye(cr, L, Y - 1, 5.8, 6.4, blink)
        _open_eye(cr, R, Y, 4.0, 4.4, blink)
    elif mood == "wink":
        _open_eye(cr, L, Y, 4.6, 5.4, blink)
        cr.set_source_rgb(*INK)
        cr.move_to(R - 5, Y + 1)
        cr.curve_to(R - 2, Y - 2, R + 2, Y - 2, R + 5, Y + 1)
        cr.stroke()
    elif mood == "love":
        p = 1 + math.sin(t * 8) * 0.12
        for x in (L, R):
            _heart(cr, x, Y, 5.2 * p)
            cr.set_source_rgb(0.93, 0.25, 0.42)
            cr.fill()
    elif mood == "dizzy":
        cr.set_source_rgb(*INK)
        cr.set_line_width(1.6)
        for x in (L, R):
            a0 = t * 8
            cr.move_to(x, Y)
            for i in range(1, 28):
                a = a0 + i * 0.5
                r = i * 0.2
                cr.line_to(x + math.cos(a) * r, Y + math.sin(a) * r)
            cr.stroke()
    else:
        _open_eye(cr, L, Y, 4.6, 5.4, blink)
        _open_eye(cr, R, Y, 4.6, 5.4, blink)


def _extras(cr, mood, t, accent):
    if mood == "sleepy":
        for i in range(2):
            ph = (t * 0.5 + i * 0.5) % 1.0
            cr.set_source_rgba(1, 1, 1, 0.85 * (1 - ph))
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(10 + i * 4)
            cr.move_to(78 + ph * 8, 26 - ph * 18 - i * 4)
            cr.show_text("z")
    elif mood == "curious":
        cr.set_source_rgb(*accent)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(22)
        cr.move_to(80, 22 + math.sin(t * 3) * 2)
        cr.show_text("?")
    elif mood == "love":
        for i in range(3):
            ph = (t * 0.6 + i / 3) % 1.0
            _heart(cr, 18 + i * 32 + math.sin(t * 3 + i) * 3, 22 - ph * 20, 3.5)
            cr.set_source_rgba(0.95, 0.3, 0.5, 1 - ph)
            cr.fill()
    elif mood == "dizzy":
        for i in range(3):
            a = t * 3 + i * 2.1
            x, y = 50 + math.cos(a) * 34, 18 + math.sin(a) * 7
            cr.set_source_rgb(1.0, 0.85, 0.3)
            _star(cr, x, y, 4)
            cr.fill()
    elif mood == "happy":
        for i in range(4):
            ph = (t * 0.8 + i / 4) % 1.0
            a = i * 1.6 + 0.4
            x = 50 + math.cos(a) * (30 + ph * 18)
            y = 40 - math.sin(a) * (18 + ph * 14)
            cr.set_source_rgba(*accent, 1 - ph)
            _star(cr, x, y, 2.6)
            cr.fill()


def _star(cr, x, y, r):
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        (cr.move_to if i == 0 else cr.line_to)(x + math.cos(a) * rr, y + math.sin(a) * rr)
    cr.close_path()


def render_png(path, size=128, mood="happy", accent=(1.0, 0.6, 0.24), species="pup"):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    draw(cr, size, size, mood, 0.3, 0.0, accent, species=species)
    surf.write_to_png(path)
