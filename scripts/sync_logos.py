#!/usr/bin/env python3
"""
3. Local Logo Mirroring & Broken-Logo Fixer (sync_logos.py)
- Downloads all tvg-logo images referenced in clean-playlist.m3u
- Resizes & optimizes them into lightweight 96x96 PNGs in logos/
- Rewrites M3U & channels.min.json logo URLs to point to your fast jsDelivr/GitHub CDN
- Replaces broken/404 logos with your reliable fallback logo
"""

import hashlib
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

M3U_PATH = os.environ.get("CLEAN_M3U", "data/clean-playlist.m3u")
JSON_PATH = os.environ.get("OUTPUT_CHANNELS_JSON", "data/channels.min.json")
LOGOS_DIR = os.environ.get("LOGOS_DIR", "logos")
REPO_SLUG = os.environ.get("GITHUB_REPOSITORY", "saeidrahmanbd/BDIX-IPTV")
CDN_BASE = os.environ.get("LOGO_CDN_BASE", f"https://cdn.jsdelivr.net/gh/{REPO_SLUG}@main/logos")
FALLBACK_LOGO = "https://raw.githubusercontent.com/saeidrahmanbd/BDIX-IPTV/main/logos/btv-national-2db28e10.png"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "channel"


def mirror_logo(item: tuple) -> tuple:
    ch_name, logo_url = item
    if not logo_url or not logo_url.startswith(("http://", "https://")):
        return logo_url, FALLBACK_LOGO

    # Already hosted on our repo/CDN
    if REPO_SLUG in logo_url and "/logos/" in logo_url:
        return logo_url, logo_url

    digest = hashlib.sha1(logo_url.encode("utf-8")).hexdigest()[:8]
    filename = f"{slugify(ch_name)}-{digest}.png"
    out_path = os.path.join(LOGOS_DIR, filename)
    cdn_url = f"{CDN_BASE}/{filename}"

    if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
        return logo_url, cdn_url

    try:
        resp = requests.get(logo_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200 or not resp.content:
            return logo_url, FALLBACK_LOGO

        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img.thumbnail((96, 96), Image.LANCZOS)

        # Center onto clean 96x96 transparent canvas for uniform TV grid alignment
        canvas = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        offset = ((96 - img.width) // 2, (96 - img.height) // 2)
        canvas.paste(img, offset, img)
        canvas.save(out_path, format="PNG", optimize=True)
        return logo_url, cdn_url
    except Exception:
        return logo_url, FALLBACK_LOGO


def main():
    os.makedirs(LOGOS_DIR, exist_ok=True)
    if not os.path.exists(M3U_PATH):
        print(f"Playlist not found at {M3U_PATH}, skipping logo sync.")
        return

    with open(M3U_PATH, "r", encoding="utf-8") as f:
        m3u_text = f.read()

    pairs = []
    seen = set()
    for line in m3u_text.splitlines():
        if line.startswith("#EXTINF:"):
            logo_m = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            comma = line.rfind(",")
            name = line[comma + 1 :].strip() if comma != -1 else "channel"
            url = logo_m.group(1).strip() if logo_m else ""
            if url and url not in seen:
                seen.add(url)
                pairs.append((name, url))

    mapping = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for orig, mirrored in pool.map(mirror_logo, pairs):
            mapping[orig] = mirrored

    def replace_logo_attr(match):
        orig_url = match.group(1).strip()
        new_url = mapping.get(orig_url, FALLBACK_LOGO if not orig_url else orig_url)
        return f'tvg-logo="{new_url}"'

    updated_m3u = re.sub(r'tvg-logo="([^"]*)"', replace_logo_attr, m3u_text, flags=re.I)
    with open(M3U_PATH, "w", encoding="utf-8") as f:
        f.write(updated_m3u)

    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            channels = json.load(f)
        for ch in channels:
            orig = ch.get("logo", "")
            ch["logo"] = mapping.get(orig, FALLBACK_LOGO if not orig else orig)
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(channels, f, separators=(",", ":"), ensure_ascii=False)

    print(f"Mirrored/verified {len(mapping)} channel logos in {LOGOS_DIR}/")


if __name__ == "__main__":
    main()
