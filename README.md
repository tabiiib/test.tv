# TABIB IPTV — Automated Repository & Smart TV Pipeline

## Included Files
1. `scripts/check_streams.py` — Validates every `.m3u8` stream concurrently (checks live segments, latency, and resolution) and outputs `data/clean-playlist.m3u` + `data/stream-health-report.json`.
2. `scripts/build_json.py` — Pre-compiles `data/channels.min.json` with your exact curated category slot matching (`News`, `Kolkata Bangla`, `Hindi Movies`, `Music`) plus `backupUrls` for <2ms Smart TV startup.
3. `scripts/sync_logos.py` — Downloads, optimizes (`96x96` PNG), and mirrors channel logos into `logos/`, fixing broken external logos automatically.
4. `scripts/generate_allowlist.py` — Extracts all active stream hostnames into `data/allowed-hosts.json` so `api/proxy.js` blocks SSRF and unauthorized proxy abuse.
5. `scripts/fetch_epg.py` — Downloads compressed XMLTV guide data and outputs a slim 6-hour `data/epg-now.json`.
6. `.github/workflows/update-iptv.yml` — Runs all 5 Python scripts automatically every 6 hours (and via manual "Run workflow" button in GitHub Actions).
7. `index.html`, `api/proxy.js`, & `vercel.json` — Updated frontend and hardened Vercel serverless proxy + security headers.

## Setup Instructions
1. Extract this ZIP into the root of your GitHub repository (`saeidrahmanbd/BDIX-IPTV`).
2. Push to `main`.
3. In GitHub, open **Actions → Update IPTV Playlist, Logos, Allowlist & EPG → Run workflow** to generate your initial `data/` and `logos/` files immediately.
