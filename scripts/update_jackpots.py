#!/usr/bin/env python3
"""
Fetches current Powerball / Mega Millions jackpot + cash-value estimates
from public state lottery pages and writes them to data/jackpots.json.

Runs on a schedule via GitHub Actions (see .github/workflows/update-jackpots.yml).
This runs server-side, so it isn't subject to browser CORS restrictions.

v2: fixed a cross-game contamination bug where a source page listing BOTH
games could cause one game's numbers to be parsed into the other game's
slot. Two defenses now:
  1. Parsing is anchored to Texas Lottery's per-game "Annuitized Jackpot
     for MM/DD/YYYY: Est. Cash Value: $X Million" phrase, which only
     appears on that specific game's own page.
  2. Every parsed result is validated against the game's real draw
     schedule (Mega Millions = Tue/Fri only, Powerball = Mon/Wed/Sat
     only). If the parsed next-draw date falls on the wrong weekday,
     the result is rejected rather than trusted -- this is what would
     have caught the original bug automatically.

If nothing valid is found, the previous good data is left untouched
rather than being overwritten with a guess.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "jackpots.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JackpotUpdater/1.1; +https://github.com/)"
}

# Texas Lottery has a dedicated page per game, so there's no other game's
# numbers on the page to accidentally match.
GAME_SOURCES = {
    "powerball": [
        "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/index.html",
    ],
    "megaMillions": [
        "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/index.html",
    ],
}

# Valid draw weekdays per game (Monday=0 ... Sunday=6)
VALID_WEEKDAYS = {
    "powerball": {0, 2, 5},       # Mon, Wed, Sat
    "megaMillions": {1, 4},       # Tue, Fri
}

# Texas Lottery's consistent phrasing: "Annuitized Jackpot for 07/28/2026:
# Est. Cash Value: $344.2 Million"
ANCHOR = re.compile(
    r"Annuitized Jackpot for (\d{2})/(\d{2})/(\d{4}):\s*Est\.?\s*Cash Value:\s*\$?\s*([\d,]+(?:\.\d+)?)\s*Million",
    re.IGNORECASE,
)
# A standalone "$X Million" / "$X,XXX,XXX" figure, used to find the
# headline jackpot amount that precedes the cash-value anchor.
AMOUNT = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*(Million)?", re.IGNORECASE)

def fetch_text(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    html = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text

def to_millions(number_str: str, has_million_word: bool) -> float:
    val = float(number_str.replace(",", ""))
    return val if has_million_word else val / 1_000_000

def parse_game(game_key: str):
    for url in GAME_SOURCES[game_key]:
        try:
            text = fetch_text(url)
        except Exception as e:
            print(f"  ! fetch failed for {url}: {e}")
            continue

        m = ANCHOR.search(text)
        if not m:
            print(f"  ! anchor phrase not found on {url}")
            continue

        mm, dd, yyyy, cash_num = m.groups()
        try:
            draw_date = datetime(int(yyyy), int(mm), int(dd))
        except ValueError:
            print(f"  ! could not parse date {mm}/{dd}/{yyyy} on {url}")
            continue

        # Weekday sanity check -- this is what would have caught the
        # original swap automatically instead of trusting bad data.
        if draw_date.weekday() not in VALID_WEEKDAYS[game_key]:
            print(
                f"  ! REJECTED: {game_key} draw date {draw_date.date()} "
                f"falls on {draw_date.strftime('%A')}, which isn't a "
                f"{game_key} draw day. Likely wrong-game contamination. Skipping."
            )
            continue

        cash = to_millions(cash_num, True)
        if not (1 <= cash <= 5000):
            print(f"  ! cash value {cash} out of sane range, skipping")
            continue

        # Find the headline jackpot amount: look at the text immediately
        # before the anchor match and take the last dollar amount there.
        window_start = max(0, m.start() - 200)
        preceding = text[window_start:m.start()]
        jackpot = None
        for am in AMOUNT.finditer(preceding):
            num, million_word = am.group(1), bool(am.group(2))
            try:
                candidate = to_millions(num, million_word)
                if 1 <= candidate <= 5000:
                    jackpot = candidate  # keep the closest (last) match
            except ValueError:
                continue

        if jackpot is None:
            # Fall back to a common jackpot:cash ratio (~44-46%) if the
            # headline figure couldn't be isolated -- better than nothing,
            # but log it clearly so it can be spot-checked.
            jackpot = round(cash / 0.45)
            print(f"  ! could not isolate headline jackpot amount; estimated ${jackpot}M from cash ratio")

        print(
            f"  \u2713 {game_key} parsed from {url}: "
            f"jackpot=${jackpot}M cash=${cash}M draw={draw_date.date()} ({draw_date.strftime('%A')})"
        )
        return jackpot, cash, draw_date.strftime("%Y-%m-%d")

    return None, None, None


def main():
    results = {}
    for game_key in ("powerball", "megaMillions"):
        print(f"Checking {game_key}...")
        jackpot, cash, next_draw = parse_game(game_key)
        if jackpot and cash:
            results[game_key] = {
                "jackpotMillions": jackpot,
                "cashMillions": cash,
                "nextDraw": next_draw,
            }
        else:
            print(f"  Keeping previous {game_key} figures (parse failed this run).")

    # Cross-game sanity check: if both parsed and somehow ended up
    # identical, something is still wrong -- refuse to write either.
    if "powerball" in results and "megaMillions" in results:
        pb, mm = results["powerball"], results["megaMillions"]
        if pb["cashMillions"] == mm["cashMillions"] and pb["jackpotMillions"] == mm["jackpotMillions"]:
            print("! Powerball and Mega Millions parsed identically -- discarding both, keeping previous data.")
            results = {}

    if not results:
        print("No valid data parsed. Leaving jackpots.json unchanged.")
        sys.exit(1)

    current = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {}
    current.update(results)
    current["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    DATA_FILE.write_text(json.dumps(current, indent=2) + "\n")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
