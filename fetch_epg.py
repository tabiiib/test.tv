#!/usr/bin/env python3
"""
5. Automated EPG (TV Guide) Slimmer (fetch_epg.py)
Downloads a compressed XMLTV EPG feed, filters only programmes matching
your curated channels for the next 6 hours, and outputs a tiny ~30KB
data/epg-now.json file for Now/Next program titles on TV & iPhone.
"""

import datetime
import gzip
import io
import json
import os
import re
import xml.etree.ElementTree as ET

import requests

EPG_XML_GZ_URL = os.environ.get("EPG_URL", "https://iptv-org.github.io/epg/guides/in/tataplay.com.epg.xml.gz")
CHANNELS_JSON = os.environ.get("OUTPUT_CHANNELS_JSON", "data/channels.min.json")
OUTPUT_EPG = os.environ.get("OUTPUT_EPG", "data/epg-now.json")
WINDOW_HOURS = int(os.environ.get("EPG_WINDOW_HOURS", "6"))


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def parse_xmltv_time(ts: str) -> datetime.datetime:
    # Format: YYYYMMDDHHMMSS +0000
    clean = ts.strip()
    dt_part = clean[:14]
    tz_part = clean[15:].strip() if len(clean) > 14 else "+0000"
    dt = datetime.datetime.strptime(dt_part, "%Y%m%d%H%M%S")
    if len(tz_part) == 5 and tz_part[0] in ("+", "-"):
        sign = 1 if tz_part[0] == "+" else -1
        hours = int(tz_part[1:3])
        mins = int(tz_part[3:5])
        tz = datetime.timezone(datetime.timedelta(hours=sign * hours, minutes=sign * mins))
    else:
        tz = datetime.timezone.utc
    return dt.replace(tzinfo=tz).astimezone(datetime.timezone.utc)


def main():
    wanted_names = {}
    if os.path.exists(CHANNELS_JSON):
        with open(CHANNELS_JSON, "r", encoding="utf-8") as f:
            for ch in json.load(f):
                k = norm_key(ch.get("name", ""))
                if k:
                    wanted_names[k] = ch["name"]
                tid = norm_key(ch.get("tvgId", ""))
                if tid:
                    wanted_names[tid] = ch["name"]

    if not wanted_names:
        print("No channels found to match EPG against.")
        return

    try:
        resp = requests.get(EPG_XML_GZ_URL, timeout=25)
        resp.raise_for_status()
        raw_bytes = resp.content
        if EPG_XML_GZ_URL.endswith(".gz") or raw_bytes[:2] == b"\x1f\x8b":
            xml_bytes = gzip.decompress(raw_bytes)
        else:
            xml_bytes = raw_bytes
    except Exception as exc:
        print(f"Skipping EPG update (source unreachable): {exc}")
        return

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_utc = now_utc + datetime.timedelta(hours=WINDOW_HOURS)

    channel_id_map = {}
    epg_data = {}

    context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
    for _, elem in context:
        if elem.tag == "channel":
            cid = elem.attrib.get("id", "")
            disp = elem.findtext("display-name") or cid
            nk_id = norm_key(cid)
            nk_disp = norm_key(disp)
            if nk_id in wanted_names:
                channel_id_map[cid] = wanted_names[nk_id]
            elif nk_disp in wanted_names:
                channel_id_map[cid] = wanted_names[nk_disp]
            elem.clear()

        elif elem.tag == "programme":
            cid = elem.attrib.get("channel", "")
            if cid in channel_id_map:
                try:
                    start_dt = parse_xmltv_time(elem.attrib["start"])
                    stop_dt = parse_xmltv_time(elem.attrib["stop"])
                    if stop_dt >= now_utc and start_dt <= cutoff_utc:
                        title = (elem.findtext("title") or "").strip()
                        ch_label = channel_id_map[cid]
                        epg_data.setdefault(ch_label, []).append(
                            {
                                "start": int(start_dt.timestamp()),
                                "stop": int(stop_dt.timestamp()),
                                "title": title,
                            }
                        )
                except Exception:
                    pass
            elem.clear()

    for ch_label in epg_data:
        epg_data[ch_label].sort(key=lambda x: x["start"])
        epg_data[ch_label] = epg_data[ch_label][:4]

    os.makedirs(os.path.dirname(OUTPUT_EPG) or ".", exist_ok=True)
    with open(OUTPUT_EPG, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": int(now_utc.timestamp()),
                "programmes": epg_data,
            },
            f,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    print(f"Exported slim EPG for {len(epg_data)} channels -> {OUTPUT_EPG}")


if __name__ == "__main__":
    main()
