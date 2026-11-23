// Vercel Serverless Function: /api/proxy.js
// TABIB IPTV — improved version
//
// Dual-mode proxy:
//  1. Manifest-only (default, HTTPS): fetch + rewrite the tiny .m3u8,
//     segments stay direct to the CDN — ~0 MB on Vercel.
//  2. On-demand HTTP mode (allowHttp=1): proxy http:// segments on
//     https:// pages, only for allowlisted hosts, with a streaming 6 MB cap.
//
// Improvements over the original:
//  - resolveUrl() uses new URL() so ../ and ./ relative paths work.
//  - SSRF guard: blocks localhost / private / link-local / metadata hosts,
//    plus a best-effort DNS check (if the hostname resolves to a private IP).
//  - Segment proxying is allowlisted (see SEGMENT_ALLOWLIST). Manifest
//    rewriting stays open to any public https host, because it is tiny.
//    Set ALLOW_ANY_HTTP_SEGMENT = true only if you accept the open-proxy risk.
//  - Fetch timeout (8s manifest / 15s segment) via AbortController.
//  - 6 MB cap is enforced while streaming, not just from Content-Length —
//    a missing/chunked header can no longer bypass it.
//  - Extension-less manifests are detected by #EXTM3U content, not just
//    by .m3u8 suffix or Content-Type.
//  - Clearer errors: 400 invalid URL, 403 blocked / not allowlisted,
//    413 too large, 504 timeout, 502 upstream failure.

import dns from "node:dns/promises";

// ---------------------------------------------------------------------------
// Config — edit this list to add a new stream host.
// Suffix match: "aynaott.com" covers tvsen5.aynaott.com, tvsen6..., etc.
// ---------------------------------------------------------------------------
const SEGMENT_ALLOWLIST = [
  "aynaott.com", // tvsen5 / tvsen6 — BDIX
  "gpcdn.net", // nkafmbewiff / byphdgllyk
  "sunplex.live", // Maasranga
  "pages.dev", // playztv-apps, starsportshindiii, etc.
];

// Only flip this to true if you understand it re-opens the proxy to any
// http:// host for segments. The client-side 5 GB cap in index.html does
// NOT protect the server — anyone can call /api/proxy directly.
const ALLOW_ANY_HTTP_SEGMENT = false;

const MAX_SEGMENT_BYTES = 6 * 1024 * 1024; // 6 MB
const MANIFEST_TIMEOUT_MS = 8000;
const SEGMENT_TIMEOUT_MS = 15000;

function hostMatchesSuffix(hostname, suffix) {
  const h = String(hostname || "").toLowerCase();
  const s = String(suffix || "").toLowerCase();
  return h === s || h.endsWith("." + s);
}

function isPrivateHostname(hostname) {
  const h = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  if (!h || h === "localhost" || h.endsWith(".local") || h.endsWith(".internal")) return true;
  if (h === "::1" || h === "::" || h === "0.0.0.0") return true;
  if (h.startsWith("127.") || h.startsWith("10.") || h.startsWith("192.168.")) return true;
  if (h.startsWith("169.254.")) return true; // link-local / cloud metadata
  if (h.startsWith("fe80:") || h.startsWith("fc") || h.startsWith("fd")) return true;
  const m172 = h.match(/^172\.(\d+)\./);
  if (m172) {
    const second = parseInt(m172[1], 10);
    if (second >= 16 && second <= 31) return true;
  }
  return false;
}

function isPrivateIp(ip) {
  return isPrivateHostname(String(ip || ""));
}

// Best-effort DNS check. On lookup error / timeout we allow the request
// (do not break playback for a DNS hiccup) — the hostname string check
// above is the hard guard.
async function resolvesToPrivateIp(hostname) {
  try {
    const addrs = await Promise.race([
      dns.lookup(hostname, { all: true }),
      new Promise((_, reject) => setTimeout(() => reject(new Error("dns timeout")), 2000)),
    ]);
    return (addrs || []).some((a) => isPrivateIp(a.address));
  } catch {
    return false;
  }
}

function resolveUrl(rel, baseDir) {
  const trimmed = String(rel || "").trim();
  if (!trimmed) return trimmed;
  try {
    // Handles absolute URLs, //protocol-relative, /absolute-path,
    // relative, ./ and ../ correctly.
    return new URL(trimmed, baseDir).href;
  } catch {
    // Fallback to the old behaviour rather than crashing the manifest.
    if (/^https?:\/\//i.test(trimmed)) return trimmed;
    if (trimmed.startsWith("//")) return "https:" + trimmed;
    return baseDir + trimmed;
  }
}

async function readWithCap(upstream, maxBytes, signal) {
  // Stream the body and stop as soon as we exceed the cap.
  if (!upstream.body || typeof upstream.body.getReader !== "function") {
    const buf = Buffer.from(await upstream.arrayBuffer());
    if (buf.length > maxBytes) {
      const err = new Error("Segment exceeds 6MB safety cap");
      err.code = "TOO_LARGE";
      throw err;
    }
    return buf;
  }
  const reader = upstream.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (signal && signal.aborted) throw new Error("Aborted");
    total += value.byteLength;
    if (total > maxBytes) {
      try { await reader.cancel(); } catch {}
      const err = new Error("Segment exceeds 6MB safety cap");
      err.code = "TOO_LARGE";
      throw err;
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks);
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }
  if (req.method !== "GET" && req.method !== "HEAD") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const targetUrl = req.query.url;
  if (!targetUrl || typeof targetUrl !== "string" || !/^https?:\/\//i.test(targetUrl)) {
    return res.status(400).json({ error: "Invalid stream URL" });
  }

  let target;
  try {
    target = new URL(targetUrl);
  } catch {
    return res.status(400).json({ error: "Invalid stream URL" });
  }

  // Hard SSRF guard, before any fetch.
  if (isPrivateHostname(target.hostname)) {
    return res.status(403).json({ error: "Blocked host" });
  }
  if (await resolvesToPrivateIp(target.hostname)) {
    return res.status(403).json({ error: "Blocked host" });
  }

  const allowHttp = req.query.allowHttp === "1" && target.protocol === "http:";
  const lowerUrl = targetUrl.toLowerCase();
  const isMediaSegment = /\.(ts|m4s|mp4|aac|mp3|key)(\?|$)/i.test(lowerUrl);

  // Segment proxying is the expensive / abusable path — allowlist it.
  if (isMediaSegment && allowHttp) {
    const allowed =
      ALLOW_ANY_HTTP_SEGMENT ||
      SEGMENT_ALLOWLIST.some((suffix) => hostMatchesSuffix(target.hostname, suffix));
    if (!allowed) {
      return res.status(403).json({
        error: "Segment host not allowlisted",
        hint: "Add the host to SEGMENT_ALLOWLIST in api/proxy.js",
      });
    }
  }

  // For normal HTTPS streams, NEVER proxy video segments on Vercel.
  if (isMediaSegment && !allowHttp) {
    res.setHeader("Cache-Control", "public, max-age=60");
    return res.redirect(302, targetUrl);
  }

  const timeoutMs = isMediaSegment ? SEGMENT_TIMEOUT_MS : MANIFEST_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const upstream = await fetch(targetUrl, {
      signal: controller.signal,
      headers: {
        "User-Agent": "Lavf/58.76.100",
        Accept: "*/*",
      },
    });

    if (!upstream.ok) {
      return res.status(upstream.status).send("Upstream error");
    }

    const contentType = (upstream.headers.get("content-type") || "").toLowerCase();

    // Binary media segment or encryption key (only allowed when allowHttp)
    if (isMediaSegment) {
      if (!allowHttp) {
        return res.redirect(302, targetUrl);
      }
      const buf = await readWithCap(upstream, MAX_SEGMENT_BYTES, controller.signal);
      res.setHeader("Content-Type", contentType || "video/mp2t");
      res.setHeader("Content-Length", String(buf.length));
      res.setHeader("Cache-Control", "public, max-age=15");
      return res.status(200).send(buf);
    }

    // Everything else: read as text, then decide manifest vs. other.
    const bodyText = await upstream.text();
    const looksLikeM3u8 =
      /\.m3u8(\?|$)/i.test(lowerUrl) ||
      contentType.includes("mpegurl") ||
      contentType.includes("x-mpegurl") ||
      bodyText.trimStart().startsWith("#EXTM3U");

    if (!looksLikeM3u8) {
      // Not a manifest (e.g. a key or other file). Don't proxy it unless
      // this is an explicitly allowed HTTP stream.
      if (!allowHttp) {
        return res.redirect(302, targetUrl);
      }
      const buf = Buffer.from(bodyText, "utf-8");
      if (buf.length > MAX_SEGMENT_BYTES) {
        return res.status(413).json({ error: "File exceeds 6MB safety cap" });
      }
      res.setHeader("Content-Type", contentType || "application/octet-stream");
      res.setHeader("Cache-Control", "public, max-age=15");
      return res.status(200).send(buf);
    }

    // M3U8 manifest text rewriting
    const finalUrl = upstream.url || targetUrl;
    const baseDir = finalUrl.substring(0, finalUrl.lastIndexOf("/") + 1);

    const rewritten = bodyText
      .split(/\r?\n/)
      .map((rawLine) => {
        const line = rawLine.trim();
        if (!line) return rawLine;

        if (line.startsWith("#")) {
          return rawLine.replace(/URI="([^"]+)"/gi, (match, uri) => {
            const absUri = resolveUrl(uri, baseDir);
            if (/\.m3u8(\?|$)/i.test(absUri)) {
              const extra = allowHttp && absUri.startsWith("http://") ? "&allowHttp=1" : "";
              return `URI="/api/proxy?mode=manifest${extra}&url=${encodeURIComponent(absUri)}"`;
            }
            if (allowHttp && absUri.startsWith("http://")) {
              return `URI="/api/proxy?allowHttp=1&url=${encodeURIComponent(absUri)}"`;
            }
            return `URI="${absUri}"`;
          });
        }

        const absUrl = resolveUrl(line, baseDir);
        if (/\.m3u8(\?|$)/i.test(absUrl)) {
          const extra = allowHttp && absUrl.startsWith("http://") ? "&allowHttp=1" : "";
          return `/api/proxy?mode=manifest${extra}&url=${encodeURIComponent(absUrl)}`;
        }
        if (allowHttp && absUrl.startsWith("http://")) {
          return `/api/proxy?allowHttp=1&url=${encodeURIComponent(absUrl)}`;
        }
        return absUrl;
      })
      .join("\n");

    res.setHeader("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).send(rewritten);
  } catch (err) {
    if (err && err.code === "TOO_LARGE") {
      return res.status(413).json({ error: "Segment exceeds 6MB safety cap" });
    }
    if (err && (err.name === "AbortError" || controller.signal.aborted)) {
      return res.status(504).json({ error: "Upstream timeout" });
    }
    return res.status(502).json({ error: "Failed to fetch stream" });
  } finally {
    clearTimeout(timer);
  }
}
