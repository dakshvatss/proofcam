"""Prepare deck assets from authentic sources only (see ../ASSET_MANIFEST.md).

Inputs (all produced locally, no model calls):
  - shots/*.png : headless-Chrome captures of the real ProofCam app serving COPIES of var/live-*.db
  - assets_raw/*.jpg : photos + stored analysis overlays exported read-only from those databases
  - icons.png + icons.json : Lucide icon sheet rendered by icons.mjs
Usage: python build_assets.py <scratch_dir> <presentation_dir>
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

scratch, pres = Path(sys.argv[1]), Path(sys.argv[2])
out = pres / "assets"
for d in ("icons", "ui", "photos"):
    (out / d).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- icons (transparent PNG, 2x cells)
meta = json.loads((scratch / "icons.json").read_text())
sheet = Image.open(scratch / "icons.png").convert("RGBA")
scale = sheet.width / (meta["cell"] * meta["cols"])
c = int(meta["cell"] * scale)
for cell in meta["cells"]:
    x, y = cell["col"] * c, cell["row"] * c
    sheet.crop((x, y, x + c, y + c)).save(out / "icons" / f"{cell['name']}_{cell['colour']}.png")
print("icons:", len(meta["cells"]))


# ---------------------------------------------------------------- UI crops (CSS px x3, phone layout 500 px wide)
def rounded(im: Image.Image, r: int) -> Image.Image:
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, fill=255)
    im.putalpha(mask)
    return im


def crop(src: str, name: str, box_css: tuple[int, int, int, int], radius: int = 0) -> None:
    im = Image.open(scratch / "shots" / f"{src}.png")
    x1, y1, x2, y2 = (v * 3 for v in box_css)
    im = im.crop((x1, y1, x2, y2))
    (rounded(im, radius) if radius else im.convert("RGB")).save(out / "ui" / f"{name}.png")
    print("ui:", name, im.size)


# Final, physical-equipment inspection (insp_92cc…, VERIFIED operator-attested)
crop("B_mobile", "B_installation", (16, 228, 484, 672), radius=48)
crop("B_mobile", "B_R1_card", (16, 695, 484, 1218), radius=48)
crop("B_mobile", "B_R1_statements", (36, 1237, 464, 1386), radius=30)
crop("B_mobile", "B_R2_card", (16, 1805, 484, 2450), radius=48)
crop("B_mobile", "B_phone_screen", (0, 0, 500, 1083))
# Synthetic-image VIOLATED inspection (insp_f1bb…): the verdict card only (see manifest for the notice above it)
crop("A_mobile", "A_violated_card", (16, 343, 484, 942), radius=48)
crop("A_mobile", "A_header", (0, 80, 500, 215))
# Landing screen
crop("landing_mobile", "landing_phone_screen", (0, 0, 500, 1083))

# ---------------------------------------------------------------- photos + stored overlays (real system output)
for f in sorted((scratch / "assets").glob("*.jpg")):
    shutil.copy(f, out / "photos" / f.name)
print("photos:", len(list((out / "photos").glob("*.jpg"))))
