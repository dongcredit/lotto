#!/usr/bin/env python3
"""Fetch Powerball / Mega Millions jackpots -> data/jackpots.json."""

import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "jackpots.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JackpotUpdater/1.2)"}

SOURCES = {
    "powerball": ["https://www.texaslottery.com/export/sites/lottery/Games/Powerball/index.html"],
    "megaMillions": ["https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/index.html"],
}
WEEKDAYS = {"powerball": {0, 2, 5}, "megaMillions": {1, 4}}

ANCHOR = re.compile(
    r"Est\.?\s*Annuitized Jackpot for (\d{1,2})/(\d{1,2})/(\d{4})\s*is:\s*"
    r"\$?\s*([\d,]+(?:\.\d+)?)\s*(Million|Billion)?\s*"
    r"Est\.?\s*Cash Value\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(Million|Billion)?",
    re.IGNORECASE)


def fetch(url):
    with urlopen(Request(url, headers=HEADERS), timeout=25) as r:
        html = r.read().decode("utf-8", errors="ignore")
    html = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html))


def mils(num, unit):
    v = float(num.replace(",", ""))
    return v * 1000 if (unit or "M").lower().startswith("b") else v


def parse(game):
    for url in SOURCES[game]:
        try:
            text = fetch(url)
        except Exception as e:
            print(f"  ! fetch failed {url}: {e}")
            continue
        m = ANCHOR.search(text)
        if not m:
            print(f"  ! anchor not found on {url} ({len(text)} chars)")
            hits = list(re.finditer(r"Jackpot|Cash Value", text, re.I))[:3]
            for h in hits:
                print(f"    ...{text[max(0, h.start()-90):h.end()+140]}...")
            if not hits:
                print(f"    no keywords found; first 300 chars: {text[:300]}")
            continue
        mo, dd, yyyy, jn, ju, cn, cu = m.groups()
        try:
            d = datetime(int(yyyy), int(mo), int(dd))
        except ValueError:
            print(f"  ! bad date {mo}/{dd}/{yyyy}")
            continue
        if d.weekday() not in WEEKDAYS[game]:
            print(f"  ! REJECTED {game}: {d.date()} is {d.strftime('%A')}, not a valid draw day")
            continue
        j, c = mils(jn, ju), mils(cn, cu)
        if not (1 <= c <= 10000 and 1 <= j <= 10000) or c > j:
            print(f"  ! implausible values j={j} c={c}")
            continue
        j = int(j) if j == int(j) else round(j, 1)
        c = int(c) if c == int(c) else round(c, 1)
        print(f"  OK {game}: jackpot=${j}M cash=${c}M draw={d.date()} ({d.strftime('%A')})")
        return j, c, d.strftime("%Y-%m-%d")
    return None, None, None


def main():
    out = {}
    for g in ("powerball", "megaMillions"):
        print(f"Checking {g}...")
        j, c, nd = parse(g)
        if j and c:
            out[g] = {"jackpotMillions": j, "cashMillions": c, "nextDraw": nd}
        else:
            print(f"  Keeping previous {g} figures.")
    if len(out) == 2:
        a, b = out["powerball"], out["megaMillions"]
        if a["jackpotMillions"] == b["jackpotMillions"] and a["cashMillions"] == b["cashMillions"]:
            print("! Both games identical -- discarding both.")
            out = {}
    if not out:
        print("No valid data. Leaving jackpots.json unchanged.")
        sys.exit(1)
    cur = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {}
    cur.update(out)
    cur["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA_FILE.write_text(json.dumps(cur, indent=2) + "\n")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
