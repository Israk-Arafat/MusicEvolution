"""
Central configuration — loads .env and exposes typed constants.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Project root ──────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_CACHE = ROOT / "data" / "cache"

# ── Billboard ─────────────────────────────────────────────────
BILLBOARD_CSV = Path(os.getenv("BILLBOARD_CSV", DATA_RAW / "billboard_hot100.csv"))

# ── MusicBrainz ───────────────────────────────────────────────
# Free — no key needed, but must rate-limit to 1 req/sec
MB_APP_NAME = "MusicEvolutionProject"
MB_APP_VERSION = "1.0"
MB_CONTACT = "student@university.edu"  # Required by MusicBrainz ToS

# ── Cache files ───────────────────────────────────────────────
MB_CACHE_FILE = DATA_CACHE / "musicbrainz_cache.json"
MERGED_OUTPUT = DATA_PROCESSED / "merged_dataset.csv"

# ── Fuzzy matching ────────────────────────────────────────────
FUZZY_THRESHOLD = 85  # minimum score (0–100) to accept a match
