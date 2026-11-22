const fs = require("fs");
const path = require("path");
const { URL } = require("url");

let cachedAllowlist = null;

function getAllowedHosts() {
  if (cachedAllowlist) return cachedAllowlist;
  try {
    const filePath = path.join(process.cwd(), "data", "allowed-hosts.json");
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    cachedAllowlist = new Set((parsed.allowed_hosts || []).map((h) => h.toLowerCase()));
  } catch (e) {
    cachedAllowlist = new Set(["raw.githubusercontent.com", "cdn.jsdelivr.net"]);
  }
  return cachedAllowlist;
}

function isPrivateHost(hostname) {
  const h = hostname.toLowerCase();
  if (h === "localhost" || h.endsWith(".local") || h.endsWith(".internal")) return true;
  if (/^(127\.|10\.|192\.168\.|169\.254\.|0\.)/.test(h)) return true;
  if (/^172\.(1[6-9]|2\d|3[0-1])\./.test(h)) return true;
  return false;
}

module.exports = async function handler(req, res) {
  const target = req.query && req.query.url;
  const allowHttp = req.query && req.query.allowHttp === "1";

  if (!target) {
    return res.status(400).json({ error: "Missing url parameter" });
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(target);
  } catch (e) {
    return res.status(400).json({ error: "Invalid target URL" });
  }

  if (parsedUrl.protocol !== "https:" && !(allowHttp && parsedUrl.protocol === "http:")) {
    return res.status(403).json({ error: "Protocol not permitted" });
  }

  const host = parsedUrl.hostname.toLowerCase();
  if (isPrivateHost(host)) {
    return res.status(403).json({ error: "Private network blocked" });
  }

  const allowedHosts = getAllowedHosts();
  if (!allowedHosts.has(host)) {
    return res.status(403).json({ error: "Host not in playlist allowlist" });
  }

  try {
    const upstream = await fetch(parsedUrl.toString(), {
      headers: {
        "User-Agent": "Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 Chrome/53.0.2785.34 Safari/537.36",
        Referer: parsedUrl.origin + "/",
      },
    });

    if (!upstream.ok) {
      return res.status(upstream.status).send("Upstream stream error");
    }

    const contentType = upstream.headers.get("content-type") || "application/vnd.apple.mpegurl";
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Content-Type", contentType);
    res.setHeader("Cache-Control", "public, s-maxage=2, stale-while-revalidate=2");

    const text = await upstream.text();
    const baseDir = parsedUrl.toString().substring(0, parsedUrl.toString().lastIndexOf("/") + 1);
    const rewritten = text
      .split(/\r?\n/)
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) return line;
        try {
          return new URL(trimmed, baseDir).toString();
        } catch (e) {
          return line;
        }
      })
      .join("\n");

    return res.status(200).send(rewritten);
  } catch (err) {
    return res.status(502).json({ error: "Proxy fetch failed" });
  }
};
