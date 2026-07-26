#!/usr/bin/env python3
"""
Fetches current Powerball / Mega Millions jackpot + cash-value estimates
from public state lottery pages and writes them to data/jackpots.json.

Runs on a schedule via GitHub Actions (see .github/workflows/update-jackpots.yml).
This runs server-side, so it isn't subject to browser CORS restrictions.

NOTE: This parses public lottery pages with regex rather than a documented
API (none of the official sites publish one). Lottery sites occasionally
change their page layout/wording, which can break parsing. If a run finds
nothing valid, it leaves the existing data file untouched rather than
overwriting good data with garbage, and exits with a warning in the logs.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "jackpots.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JackpotUpdater/1.0; +https://github.com/)"
}

# Try sources in order until one parses cleanly.
POWERBALL_SOURCES = [
    "https://nelottery.com/homeapp/lotto/28/gamedetail",
    "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/index.html",
]
MEGA_MILLIONS_SOURCES = [
    "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/index.html",
    "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Estimated_Jackpot.html",
]


def fetch_text(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    # strip tags/scripts/styles down to visible-ish text
    html = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def to_millions(number_str: str, has_million_word: bool) -> float:
    val = float(number_str.replace(",", ""))
    return val if has_million_word else val / 1_000_000


AMOUNT = r"\$?\s*([\d,]+(?:\.\d+)?)\s*(Million)?"


def find_amount(text: str, near_words):
    """Find a dollar amount that appears shortly after any of `near_words`."""
    for word in near_words:
        pattern = re.compile(word + r"[^$]{0,60}" + AMOUNT, re.IGNORECASE)
        m = pattern.search(text)
        if m:
            num, million_word = m.group(1), bool(m.group(2))
            try:
                amt = to_millions(num, million_word)
                if 1 <= amt <= 5000:  # sanity bound: $1M-$5B
                    return amt
            except ValueError:
                continue
    return None


def parse_game(sources, jackpot_words, cash_words):
    for url in sources:
        try:
            text = fetch_text(url)
        except Exception as e:
            print(f"  ! fetch failed for {url}: {e}")
            continue
        jackpot = find_amount(text, jackpot_words)
        cash = find_amount(text, cash_words)
        if jackpot and cash:
            print(f"  \u2713 parsed from {url}: jackpot=${jackpot}M cash=${cash}M")
            return jackpot, cash
        print(f"  ! could not parse both values from {url} (jackpot={jackpot}, cash={cash})")
    return None, None


def main():
    print("Checking Powerball...")
    pb_jackpot, pb_cash = parse_game(
        POWERBALL_SOURCES,
        jackpot_words=["Estimated Jackpot", "Estimated Annuity", "Jackpot"],
        cash_words=["Cash"],
    )

    print("Checking Mega Millions...")
    mm_jackpot, mm_cash = parse_game(
        MEGA_MILLIONS_SOURCES,
        jackpot_words=["Annuitized Jackpot", "Estimated Jackpot", "Jackpot"],
        cash_words=["Cash"],
    )

    if not (pb_jackpot and pb_cash) and not (mm_jackpot and mm_cash):
        print("No valid data parsed for either game. Leaving jackpots.json unchanged.")
        sys.exit(1)

    current = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {}

    if pb_jackpot and pb_cash:
        current["powerball"] = {
            "jackpotMillions": pb_jackpot,
            "cashMillions": pb_cash,
            "nextDraw": current.get("powerball", {}).get("nextDraw", ""),
        }
    else:
        print("Keeping previous Powerball figures (parse failed this run).")

    if mm_jackpot and mm_cash:
        current["megaMillions"] = {
            "jackpotMillions": mm_jackpot,
            "cashMillions": mm_cash,
            "nextDraw": current.get("megaMillions", {}).get("nextDraw", ""),
        }
    else:
        print("Keeping previous Mega Millions figures (parse failed this run).")

    current["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    DATA_FILE.write_text(json.dumps(current, indent=2) + "\n")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
