"""
main.py — Full data pipeline runner.

Run this once to build the merged dataset:
    python main.py

Then open notebooks/analysis.ipynb for the analysis.

Steps
-----
1. Load Billboard Hot 100 from CSV
2. Deduplicate to unique (title, artist) pairs for API lookups
3. Enrich with MusicBrainz (duration, genre, country, label)
4. Merge and save to data/processed/merged_dataset.csv
"""
import logging
import sys
from pathlib import Path

# Make sure src/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from config import BILLBOARD_CSV, MERGED_OUTPUT
from src.billboard import load_billboard
from src.musicbrainz import MusicBrainzEnricher
from src.merger import finalize, save_merged

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# musicbrainzngs emits INFO-level warnings about unrecognized XML fields in newer
# API responses — these are harmless; suppress them.
logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)


def run(limit: int = None, reverse: bool = False, cache_file: str = None):
    """
    Execute the full pipeline.

    Parameters
    ----------
    limit : int, optional
        If set, only process the first `limit` unique songs (useful for testing).
    reverse : bool, optional
        Process songs in reverse alphabetical order. Use on a second machine so
        it works from the Z-end while the first machine works from the A-end.
    cache_file : str, optional
        Path to a custom cache file. Use a different path on each machine so
        they don't write to the same file concurrently.
    """
    # ── Step 1: Billboard ─────────────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("Step 1/4 — Loading Billboard Hot 100")
    logger.info("═" * 60)

    if not BILLBOARD_CSV.exists():
        logger.error(
            "Billboard CSV not found at '%s'.\n"
            "  → Download from: https://www.kaggle.com/datasets/dhruvildave/billboard-the-hot-100-songs\n"
            "  → Save it to: data/raw/billboard_hot100.csv",
            BILLBOARD_CSV,
        )
        sys.exit(1)

    df = load_billboard(BILLBOARD_CSV)

    if limit:
        # Keep only the first N unique songs but all their chart appearances
        top_songs = df[["title", "artist"]].drop_duplicates().head(limit)
        df = df.merge(top_songs, on=["title", "artist"])
        logger.info("Limiting to %d unique songs for testing", limit)

    logger.info("Billboard: %d chart rows, %d unique songs", len(df), df[["title", "artist"]].nunique().max())

    # ── Step 2: MusicBrainz ───────────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("Step 2/3 — MusicBrainz enrichment")
    logger.info("  (Rate-limited to 1 req/sec — this will take a while for large datasets)")
    logger.info("  Progress is cached — safe to interrupt and resume")
    logger.info("═" * 60)

    mb_enricher = MusicBrainzEnricher(**({"cache_file": cache_file} if cache_file else {}))
    df_mb = mb_enricher.enrich(df, reverse=reverse)

    # ── Step 3: Finalize & save ───────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("Step 3/3 — Finalizing and saving")
    logger.info("═" * 60)

    merged = finalize(df_mb)
    output_path = save_merged(merged)

    logger.info("━" * 60)
    logger.info("Pipeline complete!")
    logger.info("Merged dataset → %s", output_path)
    logger.info("Rows: %d | Columns: %d", len(merged), len(merged.columns))
    logger.info("MusicBrainz match  : %.1f%%", merged["mb_duration_ms"].notna().mean() * 100)
    logger.info("━" * 60)
    logger.info("Next step: open notebooks/analysis.ipynb")

    return merged


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MusicEvolution data pipeline")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to N unique songs (for testing). Omit for full dataset."
    )
    parser.add_argument(
        "--reverse", action="store_true",
        help="Process songs in reverse order (use on a second machine to run in parallel)."
    )
    parser.add_argument(
        "--cache-file", type=str, default=None,
        help="Path to a custom cache file (e.g. data/cache/musicbrainz_cache_b.json)."
    )
    args = parser.parse_args()
    run(limit=args.limit, reverse=args.reverse, cache_file=args.cache_file)
