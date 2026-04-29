"""
MusicBrainz enrichment — fetches track duration, release date, genre tags,
artist country, and label for each song.

Uses the `musicbrainzngs` library, rate-limited to 1 req/sec (MusicBrainz ToS).
Results are cached to a JSON file so reruns skip already-fetched songs.

MusicBrainz API docs: https://musicbrainz.org/doc/MusicBrainz_API
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import musicbrainzngs
import pandas as pd
from rapidfuzz import fuzz
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tqdm import tqdm

from config import MB_APP_NAME, MB_APP_VERSION, MB_CONTACT, MB_CACHE_FILE, FUZZY_THRESHOLD

logger = logging.getLogger(__name__)

# Register the application with MusicBrainz (required by their ToS)
musicbrainzngs.set_useragent(MB_APP_NAME, MB_APP_VERSION, MB_CONTACT)
musicbrainzngs.set_rate_limit(limit_or_interval=1.0)  # max 1 req/sec


class MusicBrainzEnricher:
    """
    Enriches a songs DataFrame with data from MusicBrainz.

    Usage
    -----
    enricher = MusicBrainzEnricher()
    df_enriched = enricher.enrich(df)  # df must have 'title' and 'artist' columns
    """

    def __init__(self, cache_file: Path = MB_CACHE_FILE):
        self.cache_file = Path(cache_file)
        self.cache: dict[str, dict] = self._load_cache()

    # ── Cache I/O ─────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded %d cached MusicBrainz entries", len(data))
            return data
        return {}

    def _save_cache(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _cache_key(title: str, artist: str) -> str:
        return f"{title.lower().strip()}|{artist.lower().strip()}"

    # ── API call ──────────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _fetch_recording(self, title: str, artist: str) -> Optional[dict]:
        """
        Search MusicBrainz for a recording matching (title, artist).
        Returns a dict of extracted fields or None if not found.
        """
        # Strip characters that break Lucene query syntax (quotes, colons, etc.)
        safe_title = _sanitize_query(title)
        safe_artist = _sanitize_query(artist)
        query = f'recording:"{safe_title}" AND artist:"{safe_artist}"'
        try:
            # search_recordings does not accept 'includes' — that's only for get_recording_by_id
            result = musicbrainzngs.search_recordings(query=query, limit=5)
        except musicbrainzngs.ResponseError as exc:
            logger.warning("MusicBrainz ResponseError for '%s' – '%s': %s", title, artist, exc)
            return None

        recordings = result.get("recording-list", [])
        if not recordings:
            return None

        # Pick the best match by fuzzy-scoring title + artist
        best = _pick_best_match(recordings, title, artist)
        if best is None:
            return None

        # Fetch full detail (releases, tags, artist-credits) for the chosen recording
        try:
            detail = musicbrainzngs.get_recording_by_id(
                best["id"],
                includes=["releases", "tags", "artist-credits", "artists"],
            )
            best = detail.get("recording", best)
        except Exception as exc:
            logger.warning("Could not fetch recording detail for %s: %s", best.get("id"), exc)
            # Fall back to the search result which has partial data

        return _extract_fields(best)

    # ── Public API ────────────────────────────────────────────────────────────

    def lookup(self, title: str, artist: str) -> dict:
        """Return MusicBrainz data for a single song (uses cache)."""
        key = self._cache_key(title, artist)
        if key not in self.cache:
            self.cache[key] = self._fetch_recording(title, artist) or {}
        return self.cache[key]

    def enrich(self, df: pd.DataFrame, save_every: int = 100) -> pd.DataFrame:
        """
        Add MusicBrainz columns to `df`.

        New columns added:
            mb_duration_ms, mb_release_year, mb_genre_tags,
            mb_artist_country, mb_label
        """
        # Build the unique (title, artist) pairs to avoid redundant lookups
        pairs = df[["title", "artist"]].drop_duplicates().values.tolist()
        logger.info("Fetching MusicBrainz data for %d unique songs…", len(pairs))

        for i, (title, artist) in enumerate(tqdm(pairs, desc="MusicBrainz")):
            self.lookup(title, artist)
            if (i + 1) % save_every == 0:
                self._save_cache()

        self._save_cache()

        # Map results back to the full DataFrame
        def _row_data(row):
            return self.cache.get(self._cache_key(row["title"], row["artist"]), {})

        df = df.copy()
        df["mb_duration_ms"] = df.apply(lambda r: _row_data(r).get("duration_ms"), axis=1)
        df["mb_release_year"] = df.apply(lambda r: _row_data(r).get("release_year"), axis=1)
        df["mb_genre_tags"] = df.apply(lambda r: _row_data(r).get("genre_tags"), axis=1)
        df["mb_artist_country"] = df.apply(lambda r: _row_data(r).get("artist_country"), axis=1)
        df["mb_label"] = df.apply(lambda r: _row_data(r).get("label"), axis=1)

        filled = df["mb_duration_ms"].notna().sum()
        logger.info("MusicBrainz enrichment done: %d / %d songs matched", filled, len(df))
        return df


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_query(text: str) -> str:
    """
    Escape characters that break Lucene query syntax used by MusicBrainz.
    Removes embedded quotes and strips leading/trailing punctuation that
    causes parse errors (e.g. titles like '"B" Girls').
    """
    # Replace any double-quote with a space so the Lucene field boundary is preserved
    text = text.replace('"', ' ').replace('\\', ' ')
    # Collapse multiple spaces
    return ' '.join(text.split())


def _pick_best_match(recordings: list, title: str, artist: str) -> Optional[dict]:
    """Choose the recording whose title+artist best matches the query."""
    best_score = 0
    best_rec = None

    for rec in recordings:
        rec_title = rec.get("title", "")
        rec_artist = ""
        credits = rec.get("artist-credit", [])
        if credits and isinstance(credits[0], dict):
            rec_artist = credits[0].get("artist", {}).get("name", "")

        title_score = fuzz.token_sort_ratio(title.lower(), rec_title.lower())
        artist_score = fuzz.token_sort_ratio(artist.lower(), rec_artist.lower())
        combined = (title_score * 0.6) + (artist_score * 0.4)

        if combined > best_score:
            best_score = combined
            best_rec = rec

    if best_score < FUZZY_THRESHOLD:
        return None
    return best_rec


def _extract_fields(rec: dict) -> dict:
    """Pull the fields we care about from a MusicBrainz recording dict."""
    # Duration
    duration_ms = None
    if rec.get("length"):
        try:
            duration_ms = int(rec["length"])
        except (ValueError, TypeError):
            pass

    # Earliest release year
    release_year = None
    releases = rec.get("release-list", [])
    years = []
    label = None
    for rel in releases:
        date_str = rel.get("date", "")
        if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
            years.append(int(date_str[:4]))
        # Label info lives inside release → label-info-list
        if label is None:
            for li in rel.get("label-info-list", []):
                lbl = li.get("label", {}).get("name")
                if lbl:
                    label = lbl
                    break
    if years:
        release_year = min(years)

    # Genre tags — prefer recording tags, fall back to artist tags
    tags = [t["name"] for t in rec.get("tag-list", []) if isinstance(t, dict)]
    if not tags:
        credits = rec.get("artist-credit", [])
        if credits and isinstance(credits[0], dict):
            artist_tags = credits[0].get("artist", {}).get("tag-list", [])
            tags = [t["name"] for t in artist_tags if isinstance(t, dict)]

    # Artist country
    artist_country = None
    credits = rec.get("artist-credit", [])
    if credits and isinstance(credits[0], dict):
        artist_country = credits[0].get("artist", {}).get("country")

    return {
        "duration_ms": duration_ms,
        "release_year": release_year,
        "genre_tags": ", ".join(tags) if tags else None,
        "artist_country": artist_country,
        "label": label,
    }
