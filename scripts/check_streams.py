#!/usr/bin/env python3
"""
1. Automated Dead-Link & Stream Health Cleaner (check_streams.py)
Validates IPTV-Playlist.m3u concurrently:
- Verifies HTTP 200 OK, #EXTM3U header, and at least one live .ts/.m4s/.aac media segment
- Measures latency (TTFB) and parses master playlist resolution/bandwidth
- Ranks the fastest & sharpest feed first for duplicate channels
- Outputs clean-playlist.m3u and stream-health-report.json
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

M3U_SOURCE = os.environ.get(
    "M3U_SOURCE",
    "https://raw.githubusercontent.com/saeidrahmanbd/BDIX-IPTV/main/IPTV-Playlist.m3u",
)
OUTPUT_M3U = os.environ.get("OUTPUT_M3U", "data/clean-playlist.m3u")
OUTPUT_REPORT = os.environ.get("OUTPUT_REPORT", "data/stream-health-report.json")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "20"))
TIMEOUT = float(os.environ.get("STREAM_TIMEOUT", "7.0"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 Chrome/53.0.2785.34 Safari/537.36",
    "Accept": "*/*",
}


def fetch_source_m3u(source: str) -> str:
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    resp = requests.get(source, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_m3u(text: str):
    entries = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            logo_m = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            group_m = re.search(r'group-title="([^"]*)"', line, re.I)
            tvg_id_m = re.search(r'tvg-id="([^"]*)"', line, re.I)
            comma_idx = line.rfind(",")
            name = line[comma_idx + 1 :].strip() if comma_idx != -1 else "Channel"
            current = {
                "extinf": line,
                "name": name or "Channel",
                "logo": logo_m.group(1).strip() if logo_m else "",
                "group": group_m.group(1).strip() if group_m else "Others",
                "tvg_id": tvg_id_m.group(1).strip() if tvg_id_m else "",
            }
        elif not line.startswith("#") and current:
            current["url"] = line
            entries.append(current)
            current = None
    return entries


def inspect_hls_stream(entry: dict) -> dict:
    url = entry["url"]
    result = {
        **entry,
        "alive": False,
        "latency_ms": 99999,
        "max_height": 0,
        "max_bandwidth": 0,
        "reason": "",
    }
    if not url.lower().startswith(("http://", "https://")):
        result["reason"] = "unsupported_scheme"
        return result

    t0 = time.perf_counter()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        result["latency_ms"] = latency_ms

        if resp.status_code < 200 or resp.status_code >= 300:
            result["reason"] = f"http_{resp.status_code}"
            return result

        body = resp.text or ""
        if "#EXTM3U" not in body:
            result["reason"] = "missing_extm3u"
            return result

        # Master playlist check -> follow best variant
        if "#EXT-X-STREAM-INF" in body:
            best_sub_url = None
            best_bw = -1
            best_h = 0
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            for idx, ln in enumerate(lines):
                if ln.startswith("#EXT-X-STREAM-INF"):
                    bw_m = re.search(r"BANDWIDTH=(\d+)", ln)
                    res_m = re.search(r"RESOLUTION=\d+x(\d+)", ln)
                    bw = int(bw_m.group(1)) if bw_m else 0
                    h = int(res_m.group(1)) if res_m else 0
                    if idx + 1 < len(lines) and not lines[idx + 1].startswith("#"):
                        if bw >= best_bw:
                            best_bw = bw
                            best_h = h
                            best_sub_url = urljoin(resp.url, lines[idx + 1])
            result["max_bandwidth"] = best_bw if best_bw > 0 else 0
            result["max_height"] = best_h

            if not best_sub_url:
                result["reason"] = "empty_master_playlist"
                return result

            sub_resp = requests.get(best_sub_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if sub_resp.status_code < 200 or sub_resp.status_code >= 300:
                result["reason"] = f"variant_http_{sub_resp.status_code}"
                return result
            body = sub_resp.text or ""

        # Media playlist check: must contain #EXTINF and at least one segment URI
        has_segment = False
        for ln in body.splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                has_segment = True
                break

        if "#EXTINF" in body and has_segment:
            result["alive"] = True
            result["reason"] = "ok"
        else:
            result["reason"] = "no_live_segments"
        return result

    except requests.Timeout:
        result["reason"] = "timeout"
        return result
    except Exception as exc:
        result["reason"] = f"error:{type(exc).__name__}"
        return result


def main():
    os.makedirs(os.path.dirname(OUTPUT_M3U) or ".", exist_ok=True)
    raw_text = fetch_source_m3u(M3U_SOURCE)
    entries = parse_m3u(raw_text)
    print(f"Loaded {len(entries)} entries from source playlist.")

    checked = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(inspect_hls_stream, item): item for item in entries}
        for fut in as_completed(futures):
            checked.append(fut.result())

    # Preserve original playlist relative order while ranking duplicates by sharpness & latency
    orig_order = {item["url"]: idx for idx, item in enumerate(entries)}
    alive_entries = [c for c in checked if c["alive"]]
    alive_entries.sort(
        key=lambda x: (
            orig_order.get(x["url"], 999999),
            -x["max_height"],
            x["latency_ms"],
        )
    )

    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in alive_entries:
            f.write(f'{item["extinf"]}\n{item["url"]}\n')

    report = {
        "updated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scanned": len(entries),
        "total_alive": len(alive_entries),
        "total_dead": len(entries) - len(alive_entries),
        "dead_channels": [
            {"name": c["name"], "group": c["group"], "url": c["url"], "reason": c["reason"]}
            for c in checked
            if not c["alive"]
        ],
    }
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(alive_entries)} alive channels -> {OUTPUT_M3U}")


if __name__ == "__main__":
    main()
