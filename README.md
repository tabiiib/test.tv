# TABIB IPTV — Improved bundle

Original files are untouched in `~/workspace/user/files/`.
This folder is a deploy-ready copy with the fixes below.

## Deploy
Copy this whole folder to your Vercel project root, so the layout is:

```
index.html
manifest.json
vercel.json
api/proxy.js
icons/icon-192.png
icons/icon-512.png
```

Deploy to Vercel as before. No other step is needed.

## What changed

### `api/proxy.js` — the main fix
- **Fixed `../` / `./` URLs:** `resolveUrl()` now uses `new URL(rel, baseDir)`.
  The old string concatenation could produce `…/720p/../chunk.ts`.
- **SSRF guard:** blocks `localhost`, `127.*`, `10.*`, `192.168.*`,
  `172.16–31.*`, `169.254.*` (cloud metadata), `::1`, `.local` / `.internal`,
  plus a best-effort DNS check — if a hostname resolves to a private IP,
  it is blocked. Verified: `127.0.0.1` and `169.254.169.254` return 403.
- **Segment proxy allowlist:** proxying `.ts` / `.m4s` / `.mp4` segments
  (the expensive, abusable path) is now limited to:
  `aynaott.com`, `gpcdn.net`, `sunplex.live`, `pages.dev`.
  Manifest rewriting stays open to any public `https://` host — it is
  only a few KB. To add a host, edit `SEGMENT_ALLOWLIST` at the top of
  `api/proxy.js`. Do **not** set `ALLOW_ANY_HTTP_SEGMENT = true` unless
  you accept the open-proxy risk.
- **Real 6 MB cap:** segments are now read as a stream and aborted as
  soon as they pass 6 MB. The old code only trusted `Content-Length`,
  which a chunked response could omit.
- **Timeouts:** 8 s for manifests, 15 s for segments, via `AbortController`.
  A hanging upstream now returns 504 instead of hanging until Vercel kills it.
- **Extension-less manifests:** a body starting with `#EXTM3U` is now
  treated as a manifest, even without a `.m3u8` suffix or the right
  `Content-Type`. Previously it would have been redirected and likely
  failed on CORS.
- **Clearer errors:** 400 invalid URL, 403 blocked / not allowlisted,
  413 too large, 504 timeout, 502 upstream failure.

Verified with a local test harness:
invalid URL → 400, localhost/metadata → 403, HTTPS segment → 302 redirect,
non-allowlisted HTTP segment → 403, public Mux test manifest → 200 with
variant playlists correctly rewritten to `/api/proxy?mode=manifest&url=…`.

### `index.html` — one line only
- Added Subresource Integrity to Hls.js 0.14.17, verified two ways
  (OpenSSL and Python `hashlib` agree):
  `sha384-lZgSGurOqpGQxROgzXskCX/jiCNuL3hbgHuTuVOpzAdMhgcutK+rSq+25KsFqNlz`
- Nothing else changed — `diff` against the original shows only that line.
  Hls.js was deliberately **not** upgraded: 0.14.17 is what keeps
  2019 LG webOS 4.5 working.

### `manifest.json` — new
- Was referenced by `index.html` but missing. Now present, with
  name `TABIB IPTV`, theme/background `#041b33`, `display: standalone`,
  and local icons at `/icons/icon-192.png` and `/icons/icon-512.png`.

### `icons/` — new
- Simple TABIB play-button icons, generated locally (192 px and 512 px).

### `vercel.json` — new
- Security headers (`X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`), and long caching for icons only.
  No CSP is set — a strict CSP would break the player's inline script.

## What was deliberately NOT changed
- The player logic, channel lists, fallback chain, and quality modes
  in `index.html` — they work, and rewriting 3,175 lines risks breaking
  LG TV playback.
- The 5 GB monthly cap is still client-side only (`localStorage` in
  `index.html`). A true server-side cap needs persistent storage
  (e.g. Vercel KV / Upstash) because serverless functions are stateless.
  The allowlist + streaming cap above are the practical protections
  that work without adding a database.
- No rate limiting was added to manifests: live HLS refreshes the
  manifest every few seconds, so an aggressive limit would break playback.
