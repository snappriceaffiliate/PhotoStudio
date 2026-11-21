"""Render the SVGs to PNG/ICO with headless Chrome (exact pixel sizes, transparent where wanted)."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
B = Path(sys.argv[1])
SVG = B / "svg"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT = (HERE / "font/Sora-SemiBold.ttf").resolve()
VAR_FONT = (HERE / "font/Sora.ttf").resolve()
tmp = Path(tempfile.mkdtemp(dir=HERE))


def shot(html: str, w: int, h: int, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    page = tmp / f"{out.stem}.html"
    page.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"@font-face{{font-family:Sora;src:url('file://{VAR_FONT}');font-weight:100 800}}"
        f"html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent}}"
        "img{display:block}</style></head><body>" + html + "</body></html>"
    )
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
         "--default-background-color=00000000", f"--window-size={w},{h}", f"--screenshot={out}",
         "--allow-file-access-from-files", f"file://{page}"],
        check=True, capture_output=True,
    )
    with Image.open(out) as im:
        if im.size != (w, h):
            im.crop((0, 0, w, h)).save(out)


def img(svg, w, h, style=""):
    return f"<img src='file://{(SVG / svg).resolve()}' width='{w}' height='{h}' style='{style}'>"


RATIO = 238.5 / 46.0
# Logos, transparent.
for name in ["picksnap-logo", "picksnap-logo-on-dark", "picksnap-logo-black", "picksnap-logo-white"]:
    for w in ([600, 1200, 2400] if name == "picksnap-logo" else [1200]):
        h = round(w / RATIO)
        shot(img(f"{name}.svg", w, h), w, h, B / "png" / f"{name}-{w}.png")

# Rounded icon, transparent.
for size in [16, 32, 48, 64, 128, 256, 512, 1024]:
    shot(img("picksnap-icon.svg", size, size), size, size, B / "png" / f"picksnap-icon-{size}.png")
for v in ["black", "white"]:
    shot(img(f"picksnap-icon-{v}.svg", 512, 512), 512, 512, B / "png" / f"picksnap-icon-{v}-512.png")

# Website icons.
web = B / "web"
web.mkdir(exist_ok=True)
shutil.copy(SVG / "picksnap-icon.svg", web / "favicon.svg")
shot(img("picksnap-app-icon.svg", 180, 180), 180, 180, web / "apple-touch-icon.png")
shot(img("picksnap-icon.svg", 192, 192), 192, 192, web / "icon-192.png")
shot(img("picksnap-icon.svg", 512, 512), 512, 512, web / "icon-512.png")
shot(img("picksnap-app-icon.svg", 512, 512), 512, 512, web / "icon-maskable-512.png")
icons = [Image.open(B / "png" / f"picksnap-icon-{s}.png") for s in (16, 32, 48)]
icons[2].save(web / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=icons[:2])

# Social.
social = B / "social"
shot(img("picksnap-app-icon.svg", 640, 640), 640, 640, social / "whatsapp-profile-640.png")
shot(img("picksnap-app-icon.svg", 1024, 1024), 1024, 1024, social / "app-icon-1024.png")
lw = 640
og = (
    "<div style='width:1200px;height:630px;background:#ffffff;display:flex;flex-direction:column;"
    "align-items:center;justify-content:center;gap:34px'>"
    + img("picksnap-logo.svg", lw, round(lw / RATIO))
    + "<div style=\"font-family:Sora;font-weight:400;font-size:34px;color:#5e5950;letter-spacing:-0.3px\">"
    "Photo selection for studios</div></div>"
)
shot(og, 1200, 630, social / "og-image-1200x630.png")
cover_html = (
    "<div style='width:1500px;height:500px;background:#3b2f8f;display:flex;align-items:center;justify-content:center'>"
    + img("picksnap-logo-white.svg", 700, round(700 / RATIO)) + "</div>"
)
shot(cover_html, 1500, 500, social / "cover-1500x500.png")

shutil.rmtree(tmp)
print("done")
