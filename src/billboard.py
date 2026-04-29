"""
Billboard Hot 100 — data loading and scraping.

Two modes:
  1. load_billboard(filepath)  — load the Kaggle historical CSV (recommended)
  2. scrape_recent_chart(date) — live-scrape Billboard for any single week

Kaggle dataset: https://www.kaggle.com/datasets/dhruvildave/billboard-the-hot-100-songs
Download the CSV and place it at data/raw/billboard_hot100.csv
"""
import time
import logging
import re
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Billboard changed its HTML structure over time; this targets the current layout.
_BILLBOARD_URL = "https://www.billboard.com/charts/hot-100/{date}/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── 1. Load from CSV ─────────────────────────────────────────────────────────

def load_billboard(filepath: str | Path = None) -> pd.DataFrame:
    """
    Load the full Billboard Hot 100 history from a CSV file.

    Handles the two most common Kaggle column-name variants automatically.
    Returns a tidy DataFrame with columns:
        chart_date, rank, title, artist, last_week, peak_position, weeks_on_chart
    """
    from config import BILLBOARD_CSV
    filepath = Path(filepath or BILLBOARD_CSV)

    if not filepath.exists():
        raise FileNotFoundError(
            f"Billboard CSV not found at '{filepath}'.\n"
            "Download from: https://www.kaggle.com/datasets/dhruvildave/billboard-the-hot-100-songs\n"
            "Then place it at data/raw/billboard_hot100.csv"
        )

    df = pd.read_csv(filepath, low_memory=False)
    logger.info("Loaded %d rows from %s", len(df), filepath)

    df = _normalize_columns(df)
    df = _clean_billboard(df)
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map whatever column names the CSV uses to a standard schema."""
    col_lower = {c: c.lower().strip().replace(" ", "_").replace("-", "_") for c in df.columns}
    df = df.rename(columns=col_lower)

    rename = {}
    for col in df.columns:
        if col in ("date", "chart_date", "chart_week", "week"):
            rename[col] = "chart_date"
        elif col in ("rank", "this_week", "position", "chart_position", "current_week"):
            rename[col] = "rank"
        elif col in ("song", "title", "track", "track_name", "name"):
            rename[col] = "title"
        elif col in ("artist", "performer", "artist_name", "artists"):
            rename[col] = "artist"
        elif col in ("last_week", "last_week_position", "last_pos"):
            rename[col] = "last_week"
        elif col in ("peak_position", "peak_pos", "peak"):
            rename[col] = "peak_position"
        elif col in ("weeks_on_board", "weeks_on_chart", "weeks", "wks_on_chart", "wks.on.chart"):
            rename[col] = "weeks_on_chart"
    return df.rename(columns=rename)


def _clean_billboard(df: pd.DataFrame) -> pd.DataFrame:
    """Parse dates, cast types, strip whitespace, add decade column."""
    df["chart_date"] = pd.to_datetime(df["chart_date"], errors="coerce")
    df = df.dropna(subset=["chart_date", "title", "artist"])

    df["rank"] = pd.to_numeric(df.get("rank"), errors="coerce")
    df["peak_position"] = pd.to_numeric(df.get("peak_position"), errors="coerce")
    df["weeks_on_chart"] = pd.to_numeric(df.get("weeks_on_chart"), errors="coerce")
    df["last_week"] = pd.to_numeric(df.get("last_week"), errors="coerce")

    for col in ("title", "artist"):
        df[col] = df[col].astype(str).str.strip()

    df["year"] = df["chart_date"].dt.year
    df["decade"] = (df["year"] // 10 * 10).astype(str) + "s"

    # Deduplicate: keep the week each song had its best (lowest) rank
    df = df.sort_values(["title", "artist", "rank"])
    logger.info("Billboard data ready: %d chart entries spanning %d–%d",
                len(df), df["year"].min(), df["year"].max())
    return df.reset_index(drop=True)


# ── 2. Live scraper ───────────────────────────────────────────────────────────

def scrape_recent_chart(target_date: str | date = None, delay: float = 2.0) -> pd.DataFrame:
    """
    Scrape the Billboard Hot 100 for a single week from the live website.

    Parameters
    ----------
    target_date : 'YYYY-MM-DD' string or date object (defaults to latest chart)
    delay       : seconds to wait between retries (be polite)

    Returns a DataFrame with the same schema as load_billboard().
    """
    if target_date is None:
        # Billboard publishes on Saturdays; default to the most recent one
        today = date.today()
        days_since_saturday = (today.weekday() + 2) % 7
        target_date = today - timedelta(days=days_since_saturday)

    if isinstance(target_date, (date, datetime)):
        date_str = target_date.strftime("%Y-%m-%d")
    else:
        date_str = target_date

    url = _BILLBOARD_URL.format(date=date_str)
    logger.info("Scraping Billboard Hot 100 for week of %s …", date_str)

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Request failed: %s", exc)
        raise

    soup = BeautifulSoup(resp.text, "lxml")
    rows = []

    # Current Billboard markup: each chart entry is in a list item
    # with data attributes. We parse multiple known patterns.
    entries = soup.select("li.o-chart-results-list__item")
    if not entries:
        # Fallback: look for the JSON-LD structured data block
        rows = _parse_json_ld(soup, date_str)
    else:
        rows = _parse_html_entries(entries, date_str)

    if not rows:
        raise ValueError(
            f"Could not parse Billboard page for {date_str}. "
            "The site layout may have changed — check the URL: " + url
        )

    df = pd.DataFrame(rows)
    df = _clean_billboard(df)
    logger.info("Scraped %d entries for week %s", len(df), date_str)
    return df


def _parse_html_entries(entries, date_str: str) -> list[dict]:
    """Parse <li> chart entry elements from current Billboard HTML."""
    rows = []
    for entry in entries:
        rank_tag = entry.select_one("span.c-label")
        title_tag = entry.select_one("h3#title-of-a-story")
        artist_tag = entry.select_one("span.c-label.a-no-trucate") or \
                     entry.select_one("span.c-label.a-font-primary-s")

        if not (rank_tag and title_tag):
            continue

        rank_text = rank_tag.get_text(strip=True)
        if not rank_text.isdigit():
            continue

        rows.append({
            "chart_date": date_str,
            "rank": int(rank_text),
            "title": title_tag.get_text(strip=True),
            "artist": artist_tag.get_text(strip=True) if artist_tag else "Unknown",
        })
    return rows


def _parse_json_ld(soup: BeautifulSoup, date_str: str) -> list[dict]:
    """Fallback: extract chart data from JSON-LD or data-js attributes."""
    import json
    rows = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") == "MusicPlaylist":
                for i, track in enumerate(data.get("track", []), start=1):
                    rows.append({
                        "chart_date": date_str,
                        "rank": i,
                        "title": track.get("name", ""),
                        "artist": track.get("byArtist", {}).get("name", "Unknown"),
                    })
                break
        except (json.JSONDecodeError, AttributeError):
            continue
    return rows


def scrape_date_range(start: str, end: str, delay: float = 3.0) -> pd.DataFrame:
    """
    Scrape multiple weekly charts between start and end dates (YYYY-MM-DD).
    Sleeps `delay` seconds between requests to respect Billboard's servers.
    """
    frames = []
    current = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()

    while current <= end_date:
        try:
            frames.append(scrape_recent_chart(current))
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", current, exc)
        current += timedelta(weeks=1)
        time.sleep(delay)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
