#!/usr/bin/env python3
"""
4. Auto-Generated Domain Allowlist for /api/proxy (generate_allowlist.py)
Extracts every unique stream hostname from clean-playlist.m3u and writes
data/allowed-hosts.json so Vercel's /api/proxy blocks SSRF & unauthorized leeching.
"""

import json
import os
from urllib.parse import urlparse

M3U_PATH = os.environ.get("CLEAN_M3U", "data/clean-playlist.m3u")
OUTPUT_ALLOWLIST = os.environ.get("OUTPUT_ALLOWLIST", "data/allowed-hosts.json")

EXTRA_TRUSTED_HOSTS = [
    "raw.githubusercontent.com",
    "cdn.jsdelivr.net",
]


def main():
    hosts = set(EXTRA_TRUSTED_HOSTS)
    if os.path.exists(M3U_PATH):
        with open(M3U_PATH, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and s.lower().startswith(("http://", "https://")):
                    parsed = urlparse(s)
                    if parsed.hostname:
                        hosts.add(parsed.hostname.lower())

    sorted_hosts = sorted(hosts)
    os.makedirs(os.path.dirname(OUTPUT_ALLOWLIST) or ".", exist_ok=True)
    with open(OUTPUT_ALLOWLIST, "w", encoding="utf-8") as f:
        json.dump(
            {
                "allowed_hosts": sorted_hosts,
                "count": len(sorted_hosts),
            },
            f,
            indent=2,
        )

    print(f"Exported {len(sorted_hosts)} allowed stream hosts -> {OUTPUT_ALLOWLIST}")


if __name__ == "__main__":
    main()
