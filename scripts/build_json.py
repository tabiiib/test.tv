#!/usr/bin/env python3
"""
2. Pre-Compiled JSON Feed Builder (build_json.py)
Pre-parses clean-playlist.m3u, applies TABIB IPTV's exact curated category
slot matching (News, Kolkata Bangla, Hindi Movies, Music), attaches backupUrls
for duplicate feeds, and outputs a minified data/channels.min.json for <2ms TV boot.
"""

import json
import os
import re

INPUT_M3U = os.environ.get("CLEAN_M3U", "data/clean-playlist.m3u")
FALLBACK_M3U = os.environ.get(
    "M3U_SOURCE",
    "https://raw.githubusercontent.com/saeidrahmanbd/BDIX-IPTV/main/IPTV-Playlist.m3u",
)
OUTPUT_JSON = os.environ.get("OUTPUT_CHANNELS_JSON", "data/channels.min.json")
FALLBACK_LOGO = "https://raw.githubusercontent.com/saeidrahmanbd/BDIX-IPTV/main/logos/btv-national-2db28e10.png"

NEWS_SLOTS = [
    ["btv news", "btv world"],
    ["atn news"],
    ["somoy tv", "somoy"],
    ["independent television", "independent tv", "independent"],
    ["channel 24"],
    ["ekattor tv", "ekattor"],
    ["jamuna television", "jamuna tv", "jamuna"],
    ["news 24", "news24"],
    ["dbc news"],
    ["desh tv"],
    ["channel 1", "channel one"],
    ["star news"],
    ["btv national", "btv hd", "btv"],
    ["btv chittagong", "btv chattogram"],
    ["sangsad bangladesh", "sangsad tv", "sangsad"],
    ["channel i"],
    ["ntv"],
    ["rtv"],
    ["atn bangla"],
    ["ekushey television", "ekushey tv", "etv"],
    ["banglavision", "bangla vision"],
    ["maasranga tv", "maasranga"],
    ["boishakhi tv", "boishakhi"],
    ["my tv", "mytv"],
    ["deepto tv", "deepto"],
    ["sa tv", "satv"],
    ["nagorik tv", "nagorik"],
    ["global television", "global tv"],
    ["bijoy tv"],
    ["mohona tv", "mohona"],
]

KOLKATA_SLOTS = [
    ["star jalsha"],
    ["zee bangla"],
    ["jalsha movies", "star jalsha movies"],
    ["zee bangla sonar", "zee bangla cinema"],
    ["sony aath", "sony aat"],
    ["sun bangla"],
    ["aakash aath", "akash aath", "akash 8", "aakash 8"],
    ["sangeet bangla"],
    ["dhoom music"],
    ["bangla talkies"],
    ["dd bangla"],
    ["khushboo bangla", "khusboo bangla"],
    ["rongeen tv", "rongin tv"],
    ["colors bangla"],
    ["colors bangla cinema"],
    ["ruposhi bangla"],
    ["enterr10 bangla", "enter 10 bangla"],
    ["tara tv"],
    ["tara muzik", "tara music"],
    ["mahuaa bangla", "mahua bangla"],
]

HINDI_MOVIES_SLOTS = [
    ["star gold"],
    ["sony max"],
    ["sony movies"],
    ["zee cinema"],
    ["&pictures", "and pictures", "pictures"],
    ["colors cineplex"],
    ["star gold 2"],
    ["star gold select"],
    ["sony max 2"],
    ["sony wah"],
    ["sony max 1"],
    ["zee bollywood"],
    ["zee classic"],
    ["zee action"],
    ["&xplor hd", "&xplor", "and xplor", "xplor hd"],
    ["anmol cinema"],
    ["anmol cinema 2"],
    ["star utsav movies"],
    ["star gold romance"],
    ["star gold thrills"],
    ["colors cineplex bollywood"],
    ["colors cineplex superhits"],
    ["b4u movies"],
    ["b4u kadak"],
    ["dhamaka movies b4u", "dhamaka movies"],
    ["goldmines"],
    ["goldmines 2"],
    ["goldmines action"],
    ["goldmines bollywood"],
    ["goldmines movies"],
    ["goldmines movies 2", "goldmines movies"],
    ["all time movies"],
    ["shemaroo josh"],
    ["bollygold", "nh bollygold"],
    ["nh bollyflix", "bollyflix"],
    ["bollywood old"],
    ["hindi movie classic", "hindi classic 24", "hindi movie classic 24"],
    ["chhaya chitram"],
    ["india talkies"],
    ["the movie club", "movie club"],
    ["manoranjan tv"],
    ["manoranjan prime"],
    ["housefull movies"],
    ["maha movies"],
    ["bflix movies"],
    ["cinema tv india", "cinema tv"],
    ["wow cinema one", "wow cinema"],
    ["enterr10", "enter 10"],
    ["utv movies"],
    ["utv action"],
    ["movies ok"],
]

MUSIC_SLOTS = [
    ["gaan bangla"],
    ["sangeet bangla"],
    ["dhoom music"],
    ["bangla talkies"],
    ["music fatafati"],
    ["9xm"],
    ["b4u music"],
    ["mastiii", "masti"],
    ["mtv beats"],
    ["9x jalwa"],
    ["zoom"],
    ["zing"],
    ["songdew tv", "songdew"],
    ["vh1"],
    ["9xo"],
]


def normalize_title(s: str) -> str:
    cleaned = re.sub(r"[^a-z0-9&]+", " ", str(s or "").lower())
    return re.sub(r"\s+", " ", f" {cleaned} ")


def score_tv_playability(ch: dict) -> int:
    url = ch["url"].lower()
    name = ch["name"].lower()
    grp = ch["group"].lower()
    score = 0
    if not url.startswith("http"):
        return -999
    if ".m3u8" in url:
        score += 50
    elif ".mpd" in url or url.startswith("rtmp://"):
        score -= 80
    if any(h in url for h in ("aynaott.com", "gpcdn.net", "sunplex.live", "pages.dev")):
        score += 25
    if url.startswith("https://"):
        score += 8
    if any(r in name for r in (" uk", " usa", " europe", " canada")):
        score -= 18
    if " hd" in name or " fhd" in name:
        score += 5
    if "bangladesh" in grp:
        score += 35
    score -= min(15, len(name) // 4)
    return score


def is_unreliable_variant(ch: dict, norm: str) -> bool:
    combined = norm + normalize_title(ch.get("group", "")) + normalize_title(ch.get("url", ""))
    return bool(re.search(r" (?:review|backup|bkp|bak|mirror|test|demo|offline|broken|server|alt|link)[0-9]* ", combined))


def matches_keywords(norm: str, keywords: list) -> bool:
    return any(f" {kw} " in norm for kw in keywords)


def tag_slots(channels: list, slots: list, flag_key: str, rank_key: str, category_type: str):
    used_urls = set()
    meta = [{"norm": normalize_title(c["name"]), "score": score_tv_playability(c)} for c in channels]

    for s_idx, keywords in enumerate(slots):
        candidates = []
        primary_kw = keywords[0]

        for i, ch in enumerate(channels):
            if ch.get(flag_key) or ch["url"] in used_urls or ch["isHttpOnly"]:
                continue
            norm = meta[i]["norm"]
            score = meta[i]["score"]
            if score < -50 or is_unreliable_variant(ch, norm):
                continue

            if category_type == "news" and primary_kw == "btv national":
                if any(x in norm for x in (" news ", " chittagong ", " chattogram ")):
                    continue
            elif category_type == "kolkata":
                if primary_kw == "star jalsha" and " movies " in norm:
                    continue
                if primary_kw == "zee bangla" and (" cinema " in norm or " sonar " in norm):
                    continue
                if primary_kw == "colors bangla" and " cinema " in norm:
                    continue
            elif category_type == "hindi":
                if primary_kw == "star gold" and any(x in norm for x in (" 2 ", " select ", " romance ", " thrills ")):
                    continue
                if primary_kw == "sony max" and (" 1 " in norm or " 2 " in norm):
                    continue
                if primary_kw == "colors cineplex" and (" bollywood " in norm or " superhits " in norm):
                    continue
                if primary_kw == "anmol cinema" and " 2 " in norm:
                    continue
                if primary_kw == "goldmines" and any(x in norm for x in (" 2 ", " action ", " bollywood ", " movies ")):
                    continue
                if primary_kw == "enterr10" and " bangla " in norm:
                    continue
                if primary_kw == "&pictures" and (" zee " in norm or " sony " in norm):
                    continue
            elif category_type == "music":
                if primary_kw == "zoom" and " sports " in norm:
                    continue

            if matches_keywords(norm, keywords):
                candidates.append((score, i))

        if candidates:
            candidates.sort(key=lambda x: -x[0])
            best_idx = candidates[0][1]
            channels[best_idx][flag_key] = True
            channels[best_idx][rank_key] = s_idx + 1
            used_urls.add(channels[best_idx]["url"])

            # Store up to 3 backup stream URLs for seamless mid-stream failover
            backups = [channels[idx]["url"] for _, idx in candidates[1:4] if channels[idx]["url"] != channels[best_idx]["url"]]
            if backups:
                existing = channels[best_idx].setdefault("backupUrls", [])
                for b in backups:
                    if b not in existing:
                        existing.append(b)


def load_m3u_text() -> str:
    if os.path.exists(INPUT_M3U) and os.path.getsize(INPUT_M3U) > 50:
        with open(INPUT_M3U, "r", encoding="utf-8") as f:
            return f.read()
    import requests
    resp = requests.get(FALLBACK_M3U, timeout=15)
    resp.raise_for_status()
    return resp.text


def main():
    text = load_m3u_text()
    channels = []
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            logo_m = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            group_m = re.search(r'group-title="([^"]*)"', line, re.I)
            tvg_id_m = re.search(r'tvg-id="([^"]*)"', line, re.I)
            comma = line.rfind(",")
            name = line[comma + 1 :].strip() if comma != -1 else "Channel"
            cur = {
                "name": name or "Channel",
                "logo": (logo_m.group(1).strip() if logo_m and logo_m.group(1).strip() else FALLBACK_LOGO),
                "group": (group_m.group(1).strip() if group_m and group_m.group(1).strip() else "Others"),
                "tvgId": tvg_id_m.group(1).strip() if tvg_id_m else "",
            }
        elif not line.startswith("#") and cur:
            channels.append(
                {
                    "num": len(channels) + 1,
                    "name": cur["name"],
                    "logo": cur["logo"],
                    "group": cur["group"],
                    "tvgId": cur["tvgId"],
                    "url": line,
                    "isHttpOnly": line.lower().startswith("http://"),
                    "isNews": False,
                    "newsRank": 9999,
                    "isKolkata": False,
                    "kolkataRank": 9999,
                    "isHindiMovies": False,
                    "hindiMoviesRank": 9999,
                    "isMusic": False,
                    "musicRank": 9999,
                }
            )
            cur = None

    tag_slots(channels, NEWS_SLOTS, "isNews", "newsRank", "news")
    tag_slots(channels, KOLKATA_SLOTS, "isKolkata", "kolkataRank", "kolkata")
    tag_slots(channels, HINDI_MOVIES_SLOTS, "isHindiMovies", "hindiMoviesRank", "hindi")
    tag_slots(channels, MUSIC_SLOTS, "isMusic", "musicRank", "music")

    os.makedirs(os.path.dirname(OUTPUT_JSON) or ".", exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(channels, f, separators=(",", ":"), ensure_ascii=False)

    print(f"Compiled {len(channels)} channels -> {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
