"""Build the PickSnap SVG logo files: tick-horizon icon + 'picksnap' in Sora SemiBold, outlined."""
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
SVG = OUT / "svg"
SVG.mkdir(parents=True, exist_ok=True)

INDIGO, CORAL, SUN, INK, WHITE = "#3b2f8f", "#ff6b5a", "#ffd9a0", "#1c1a17", "#ffffff"

# ---- text outlines -------------------------------------------------------------------
FONT_PX = 40.0
TRACKING = -0.03  # em, as in the chosen design (-1.2px at 40px)
var = TTFont(HERE / "font/Sora.ttf")
static = instantiateVariableFont(var, {"wght": 600})
static.save(HERE / "font/Sora-SemiBold.ttf")
upm = static["head"].unitsPerEm
asc, desc = static["hhea"].ascent, -static["hhea"].descent
glyphs = static.getGlyphSet()
order = static.getGlyphOrder()

blob = hb.Blob.from_file_path(str(HERE / "font/Sora-SemiBold.ttf"))
hbfont = hb.Font(hb.Face(blob))
buf = hb.Buffer()
buf.add_str("picksnap")
buf.guess_segment_properties()
hb.shape(hbfont, buf, {"kern": True, "liga": False})

s = FONT_PX / upm
pen_x = 0.0
runs = {"pick": [], "snap": []}
ink_right = 0.0
for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
    name = order[info.codepoint]
    svgpen = SVGPathPen(glyphs)
    x0 = pen_x + pos.x_offset * s
    glyphs[name].draw(TransformPen(svgpen, (s, 0, 0, -s, x0, 0)))  # baseline at y=0
    runs["pick" if info.cluster < 4 else "snap"].append(svgpen.getCommands())
    pen_x += pos.x_advance * s + TRACKING * FONT_PX
    ink_right = pen_x - TRACKING * FONT_PX
text_width = ink_right
pick_d = " ".join(runs["pick"])
snap_d = " ".join(runs["snap"])

# ---- lockup geometry (in px at the 40px design size) ---------------------------------
ICON = 46.0
GAP = 12.0
# CSS line-height:1 centres the em box on the icon; reproduce that.
line_top = (ICON - FONT_PX) / 2
content = (asc + desc) * s
baseline = line_top + (FONT_PX - content) / 2 + asc * s
TEXT_X = ICON + GAP
WIDTH = TEXT_X + text_width
HEIGHT = ICON

# Icon in its own 68-unit box (source coords 6..74).
def icon_parts(frame, horizon, sun, uid, mono_cutout=False, full_bleed=False):
    rx = 0 if full_bleed else 16
    rect = f'<rect x="6" y="6" width="68" height="68" rx="{rx}"/>'
    horizon_path = '<path d="M0 40L30 62L80 18V80H0Z"/>'
    sun_c = '<circle cx="54" cy="22" r="7"/>'
    if mono_cutout:
        return (
            f'<defs><mask id="{uid}m" maskUnits="userSpaceOnUse" x="6" y="6" width="68" height="68">'
            f'<rect x="6" y="6" width="68" height="68" rx="{rx}" fill="#fff"/>'
            # One colour: the photo stays whole; the tick horizon is a gap line through it.
            f'<path d="M0 40L30 62L80 18" fill="none" stroke="#000" stroke-width="7" '
            f'stroke-linejoin="round"/><g fill="#000">{sun_c}</g></mask></defs>'
            f'<rect x="6" y="6" width="68" height="68" rx="{rx}" fill="{frame}" mask="url(#{uid}m)"/>'
        )
    return (
        f'<defs><clipPath id="{uid}c">{rect}</clipPath></defs>'
        f'<rect x="6" y="6" width="68" height="68" rx="{rx}" fill="{frame}"/>'
        f'<circle cx="54" cy="22" r="7" fill="{sun}"/>'
        f'<path d="M0 40L30 62L80 18V80H0Z" fill="{horizon}" clip-path="url(#{uid}c)"/>'
    )


def fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def write(name, body, w, h, title):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(w)} {fmt(h)}" '
        f'width="{fmt(w * 4)}" height="{fmt(h * 4)}" role="img" aria-label="{title}">'
        f"<title>{title}</title>{body}</svg>\n"
    )
    (SVG / name).write_text(svg)


def icon_group(x, y, size, **kw):
    k = size / 68
    return f'<g transform="translate({fmt(x)} {fmt(y)}) scale({fmt(k)}) translate(-6 -6)">{icon_parts(**kw)}</g>'


def text_group(pick_fill, snap_fill, x=TEXT_X, y=None):
    y = baseline if y is None else y
    return (
        f'<g transform="translate({fmt(x)} {fmt(y)})">'
        f'<path fill="{pick_fill}" d="{pick_d}"/><path fill="{snap_fill}" d="{snap_d}"/></g>'
    )


def lockup(name, title, icon_kw, pick_fill, snap_fill):
    body = icon_group(0, 0, ICON, **icon_kw) + text_group(pick_fill, snap_fill)
    write(name, body, WIDTH, HEIGHT, title)


colour = dict(frame=INDIGO, horizon=CORAL, sun=SUN)
lockup("picksnap-logo.svg", "PickSnap", dict(colour, uid="a"), INK, INDIGO)
lockup("picksnap-logo-on-dark.svg", "PickSnap", dict(colour, uid="b"), WHITE, CORAL)
lockup("picksnap-logo-black.svg", "PickSnap", dict(frame=INK, horizon="", sun="", uid="c", mono_cutout=True), INK, INK)
lockup("picksnap-logo-white.svg", "PickSnap", dict(frame=WHITE, horizon="", sun="", uid="d", mono_cutout=True), WHITE, WHITE)

# Wordmark alone, tight to the letters' height box.
top = baseline - asc * s
write("picksnap-wordmark.svg", text_group(INK, INDIGO, x=0, y=asc * s - (desc * 0)), text_width, (asc + desc) * s, "PickSnap")
write("picksnap-wordmark-on-dark.svg", text_group(WHITE, CORAL, x=0, y=asc * s), text_width, (asc + desc) * s, "PickSnap")

# Icons (68x68 box, rounded).
def icon_file(name, **kw):
    write(name, icon_group(0, 0, 68, **kw), 68, 68, "PickSnap")

icon_file("picksnap-icon.svg", **colour, uid="e")
icon_file("picksnap-icon-black.svg", frame=INK, horizon="", sun="", uid="f", mono_cutout=True)
icon_file("picksnap-icon-white.svg", frame=WHITE, horizon="", sun="", uid="g", mono_cutout=True)
# Full-bleed square for app stores / Apple touch / maskable / WhatsApp (the platform rounds or crops it).
icon_file("picksnap-app-icon.svg", **colour, uid="h", full_bleed=True)

print(f"lockup {WIDTH:.1f} x {HEIGHT:.1f}, text {text_width:.1f}, baseline {baseline:.2f}")
