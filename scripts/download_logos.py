"""Download sportsbook favicons and auto-trim padding so logos sit flush.

Reads domains from web/lib/books.ts (looks for `domain: "..."`), pulls each via
Google's favicon service at 128px, crops transparent or solid-background
padding, writes PNG to web/public/logos/<domain>.png.

Run once after adding/updating domains in the book registry.

    $ source .venv/bin/activate
    $ python scripts/download_logos.py
"""
from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parent.parent
BOOKS_TS = ROOT / "web" / "lib" / "books.ts"
OUT_DIR = ROOT / "web" / "public" / "logos"
FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=128"


def extract_domains(text: str) -> list[str]:
    return sorted(set(re.findall(r'domain:\s*"([^"]+)"', text)))


def trim(img: Image.Image) -> Image.Image:
    """Crop transparent or solid-colour padding from the edges of `img`."""
    img = img.convert("RGBA")
    corner = img.getpixel((0, 0))

    if isinstance(corner, tuple) and len(corner) == 4 and corner[3] == 0:
        # Transparent corner → bbox of non-zero alpha
        bbox = img.getbbox()
    else:
        # Solid background → diff against corner colour
        bg = Image.new("RGBA", img.size, corner if isinstance(corner, tuple) else (255, 255, 255, 255))
        bbox = ImageChops.difference(img, bg).getbbox()

    if bbox:
        return img.crop(bbox)
    return img


def main() -> int:
    domains = extract_domains(BOOKS_TS.read_text())
    if not domains:
        print("No domains found in books.ts", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ok = skipped = 0
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for domain in domains:
            url = FAVICON_URL.format(domain=domain)
            try:
                resp = client.get(url)
            except httpx.HTTPError as e:
                print(f"  skip {domain} (fetch error: {e})")
                skipped += 1
                continue
            if resp.status_code != 200 or not resp.content:
                print(f"  skip {domain} ({resp.status_code})")
                skipped += 1
                continue
            try:
                img = Image.open(BytesIO(resp.content))
            except Exception as e:
                print(f"  skip {domain} (decode error: {e})")
                skipped += 1
                continue

            trimmed = trim(img)

            # Reject Google's default globe fallback — it's ~48×48 to ~96×96
            # and comes through when the site has no favicon. Low-res inputs
            # upscaled to 128 always yield a small trimmed result.
            if max(trimmed.size) < 20:
                print(f"  skip {domain} (too small after trim: {trimmed.size})")
                skipped += 1
                continue

            out_path = OUT_DIR / f"{domain}.png"
            trimmed.save(out_path, "PNG", optimize=True)
            print(f"  ok   {domain:28} {trimmed.size[0]:>3}×{trimmed.size[1]:>3}")
            ok += 1

    print(f"\nWrote {ok} logos, skipped {skipped}, to {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
