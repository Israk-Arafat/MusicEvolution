"""
Finalizes the MusicBrainz-enriched Billboard DataFrame into a clean,
analysis-ready dataset and saves it to CSV.
"""
import logging
from pathlib import Path

import pandas as pd

from config import MERGED_OUTPUT

logger = logging.getLogger(__name__)


def finalize(mb_df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive useful columns and reorder the MusicBrainz-enriched DataFrame
    into the final analysis-ready form.
    """
    assert "mb_duration_ms" in mb_df.columns, "Run MusicBrainzEnricher.enrich() first"

    merged = mb_df.copy()
    merged = _derive_columns(merged)
    merged = _reorder_columns(merged)

    logger.info(
        "Dataset ready: %d rows, %d columns. MusicBrainz fill: %.1f%%",
        len(merged),
        len(merged.columns),
        merged["mb_duration_ms"].notna().mean() * 100,
    )
    return merged


def merge_all(billboard_df, mb_df, sp_df=None) -> pd.DataFrame:
    """Backwards-compat shim — delegates to finalize()."""
    return finalize(mb_df)


def _derive_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add analysis-friendly derived columns."""
    df = df.copy()

    # ── Duration (seconds) from MusicBrainz ──────────────────────────────────
    df["duration_sec"] = (df["mb_duration_ms"] / 1000).round(1)
    df["duration_min"] = (df["mb_duration_ms"] / 60_000).round(2)

    # ── Decade bucket ─────────────────────────────────────────────────────────
    if "decade" not in df.columns:
        df["decade"] = (df["year"] // 10 * 10).astype(str) + "s"

    # ── Primary genre (first tag) ─────────────────────────────────────────────
    if "mb_genre_tags" in df.columns:
        df["primary_genre"] = df["mb_genre_tags"].apply(
            lambda x: str(x).split(",")[0].strip() if pd.notna(x) else None
        )

    return df


def _reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Put the most useful columns first."""
    priority = [
        "chart_date", "year", "decade", "rank", "title", "artist",
        "peak_position", "weeks_on_chart",
        "duration_sec", "duration_min", "mb_duration_ms",
        "primary_genre", "mb_genre_tags", "mb_artist_country", "mb_label",
        "mb_release_year", "last_week",
    ]
    existing_priority = [c for c in priority if c in df.columns]
    rest = [c for c in df.columns if c not in existing_priority]
    return df[existing_priority + rest]


def save_merged(df: pd.DataFrame, output: Path = MERGED_OUTPUT) -> Path:
    """Save the merged DataFrame to CSV."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    logger.info("Saved merged dataset → %s (%d rows)", output, len(df))
    return output


def load_merged(filepath: Path = MERGED_OUTPUT) -> pd.DataFrame:
    """Load the saved merged dataset for analysis."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(
            f"Merged dataset not found at '{filepath}'.\n"
            "Run main.py first to build it."
        )
    df = pd.read_csv(filepath, low_memory=False)
    df["chart_date"] = pd.to_datetime(df["chart_date"], errors="coerce")
    logger.info("Loaded merged dataset: %d rows, %d columns", len(df), len(df.columns))
    return df
