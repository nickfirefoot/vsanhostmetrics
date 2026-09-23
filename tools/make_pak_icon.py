#!/usr/bin/env python3
"""Turn a source artwork PNG into the management pack icon.

    python3 tools/make_pak_icon.py <source.png> [dest.png]

The SDK requires the pak icon to be PNG and exactly 256x256. mp-build does NOT
enforce that -- only mp-init validates, and we do not use mp-init because it
self-deletes its project on this host (see REPORT.md 1). So a wrong-sized icon
builds clean and only misbehaves at install time, with nothing in the build
output explaining why. This script is the enforcement point.

Two transforms beyond the resize:

* The background is keyed to transparent by flood-filling inward from the
  corners. A plain lightness threshold would also eat the pale highlights in
  the artwork; flood fill only removes background actually connected to an
  edge. Operations renders solution icons against both light and dark chrome,
  so a baked-in near-white square shows as a bright tile in dark mode.
* The canvas is padded to square before scaling, so a non-square source is not
  distorted. The subject keeps its proportions and gains margin instead.
"""
import sys

from PIL import Image, ImageDraw

SIZE = 256
# Background sampled at (216,216,216); the artwork's darkest wood is far from
# it, so a generous tolerance is safe and copes with JPEG-ish noise.
THRESH = 40


def make_icon(src_path: str, dest_path: str) -> None:
    src = Image.open(src_path).convert("RGBA")
    width, height = src.size

    # Flood fill from every corner with a colour that cannot occur in the
    # artwork, then turn exactly that colour into alpha.
    KEY = (255, 0, 255)
    flat = src.convert("RGB")
    for xy in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ImageDraw.floodfill(flat, xy, KEY, thresh=THRESH)

    keyed = Image.new("RGBA", src.size, (0, 0, 0, 0))
    keyed.paste(src, (0, 0))
    pixels = keyed.load()
    flat_pixels = flat.load()
    cleared = 0
    for y in range(height):
        for x in range(width):
            if flat_pixels[x, y] == KEY:
                pixels[x, y] = (0, 0, 0, 0)
                cleared += 1

    # Pad to square so the resize cannot distort the subject.
    side = max(width, height)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(keyed, ((side - width) // 2, (side - height) // 2))

    icon = square.resize((SIZE, SIZE), Image.LANCZOS)
    icon.save(dest_path, "PNG", optimize=True)

    check = Image.open(dest_path)
    assert check.size == (SIZE, SIZE), check.size
    assert check.format == "PNG", check.format
    pct = 100 * cleared / (width * height)
    print(f"  source      {width}x{height}")
    print(f"  background  {cleared} px cleared to alpha ({pct:.0f}%)")
    print(f"  wrote       {dest_path}  {check.size[0]}x{check.size[1]} PNG")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    make_icon(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "pak_icon.png")
