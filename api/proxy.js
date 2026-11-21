// Vercel Serverless Function: /api/proxy.js
// Dual-Mode Proxy:
// 1. Default (HTTPS streams): Manifest-only (~0 MB Fast Origin Transfer). Rewrites segments directly to CDN.
// 2. On-Demand HTTP Mode (allowHttp=1): Proxies http:// streams on https:// pages ONLY when the user
//    explicitly clicks a channel in the separated HTTP (BDIX) tab (protected by a 5 GB client budget cap).

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  const targetUrl = req.query.url;
  if (!targetUrl || !/^https?:\/\//i.test(targetUrl)) {
    return res.status(400).json({ error: "Invalid stream URL" });
  }

  const allowHttp = req.query.allowHttp === "1" && /^http:\/\//i.test(targetUrl);
  const lowerUrl = targetUrl.toLowerCase();
  const isMediaSegment = /\.(ts|m4s|mp4|aac|mp3|key)(\?|$)/i.test(lowerUrl);

  // For normal HTTPS streams (allowHttp !== "1"), NEVER proxy video segments on Vercel.
  if (isMediaSegment && !allowHttp) {
    res.setHeader("Cache-Control", "public, max-age=60");
    return res.redirect(302, targetUrl);
  }

  try {
    const upstream = await fetch(targetUrl, {
      headers: {
        "User-Agent": "Lavf/58.76.100",
        "Accept": "*/*"
      }
    });

    if (!upstream.ok) {
      return res.status(upstream.status).send("Upstream error");
    }

    const contentType = (upstream.headers.get("content-type") || "").toLowerCase();
    const looksLikeM3u8 =
      /\.m3u8(\?|$)/i.test(lowerUrl) ||
      contentType.includes("mpegurl") ||
      contentType.includes("x-mpegurl");

    // Binary media segment or encryption key (only allowed when allowHttp === true)
    if (isMediaSegment || !looksLikeM3u8) {
      if (!allowHttp) {
        return res.redirect(302, targetUrl);
      }
      const contentLen = parseInt(upstream.headers.get("content-length") || "0", 10);
      if (contentLen > 6 * 1024 * 1024) {
        return res.status(413).json({ error: "Segment exceeds 6MB safety cap" });
      }
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.setHeader("Content-Type", contentType || "video/mp2t");
      res.setHeader("Cache-Control", "public, max-age=15");
      return res.status(200).send(buf);
    }

    // M3U8 Manifest Text Rewriting
    const finalUrl = upstream.url || targetUrl;
    const baseDir = finalUrl.substring(0, finalUrl.lastIndexOf("/") + 1);
    const originMatch = finalUrl.match(/^(https?:\/\/[^\/]+)/i);
    const baseOrigin = originMatch ? originMatch[1] : "";

    const bodyText = await upstream.text();

    const rewritten = bodyText
      .split(/\r?\n/)
      .map((rawLine) => {
        const line = rawLine.trim();
        if (!line) return rawLine;

        if (line.startsWith("#")) {
          return rawLine.replace(/URI="([^"]+)"/gi, (match, uri) => {
            const absUri = resolveUrl(uri, baseDir, baseOrigin);
            if (/\.m3u8(\?|$)/i.test(absUri)) {
              const extra = allowHttp && /^http:\/\//i.test(absUri) ? "&allowHttp=1" : "";
              return `URI="/api/proxy?mode=manifest${extra}&url=${encodeURIComponent(absUri)}"`;
            }
            if (allowHttp && /^http:\/\//i.test(absUri)) {
              return `URI="/api/proxy?allowHttp=1&url=${encodeURIComponent(absUri)}"`;
            }
            return `URI="${absUri}"`;
          });
        }

        const absUrl = resolveUrl(line, baseDir, baseOrigin);
        if (/\.m3u8(\?|$)/i.test(absUrl)) {
          const extra = allowHttp && /^http:\/\//i.test(absUrl) ? "&allowHttp=1" : "";
          return `/api/proxy?mode=manifest${extra}&url=${encodeURIComponent(absUrl)}`;
        }
        if (allowHttp && /^http:\/\//i.test(absUrl)) {
          return `/api/proxy?allowHttp=1&url=${encodeURIComponent(absUrl)}`;
        }
        return absUrl;
      })
      .join("\n");

    res.setHeader("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).send(rewritten);
  } catch (err) {
    return res.status(502).json({ error: "Failed to fetch stream" });
  }
}

function resolveUrl(rel, baseDir, baseOrigin) {
  if (/^https?:\/\//i.test(rel)) return rel;
  if (rel.startsWith("//")) return "https:" + rel;
  if (rel.startsWith("/")) return baseOrigin + rel;
  return baseDir + rel;
}
