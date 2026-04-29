"""
Analysis and visualization helpers.

Each function takes the merged DataFrame and returns a figure or summary table.
Designed to be called from the Jupyter notebook (notebooks/analysis.ipynb).
"""
import logging

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns

logger = logging.getLogger(__name__)

# ── Global style ──────────────────────────────────────────────────────────────
sns.set_theme(style="darkgrid", palette="muted", font_scale=1.1)
DECADE_ORDER = ["1950s", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]


def load_merged(filepath=None) -> pd.DataFrame:
    """Convenience re-export so notebooks only need to import from src.analysis."""
    from src.merger import load_merged as _load
    return _load(filepath)


# ── 1. Song duration over time ────────────────────────────────────────────────

def plot_duration_over_time(df: pd.DataFrame, by: str = "year") -> plt.Figure:
    """
    Line plot of median song duration (in seconds) per year or decade.

    Parameters
    ----------
    by : 'year' or 'decade'
    """
    sub = df.dropna(subset=["duration_sec"])
    if sub.empty:
        raise ValueError("No duration data available. Check MusicBrainz/Spotify enrichment.")

    grouped = sub.groupby(by)["duration_sec"].median().reset_index()

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(grouped[by].astype(str), grouped["duration_sec"], marker="o", linewidth=2)
    ax.set_title("Median Song Duration Over Time (Hot 100 charting songs)")
    ax.set_xlabel(by.capitalize())
    ax.set_ylabel("Duration (seconds)")
    ax.axhline(210, color="red", linestyle="--", linewidth=0.8, label="3:30 min")
    ax.legend()
    _rotate_xlabels(ax, by)
    fig.tight_layout()
    return fig


# ── 2. Genre shifts ───────────────────────────────────────────────────────────

def plot_genre_shifts(df: pd.DataFrame, top_n: int = 8) -> plt.Figure:
    """
    Stacked bar chart of top genre tag shares per decade.
    """
    sub = df.dropna(subset=["primary_genre", "decade"]).copy()
    if sub.empty:
        raise ValueError("No genre data available. Check MusicBrainz enrichment.")

    # Keep only decades in DECADE_ORDER that exist in data
    present_decades = [d for d in DECADE_ORDER if d in sub["decade"].unique()]

    # Find overall top-N genres
    top_genres = sub["primary_genre"].value_counts().head(top_n).index.tolist()
    sub["genre_bucket"] = sub["primary_genre"].where(
        sub["primary_genre"].isin(top_genres), other="Other"
    )

    pivot = (
        sub.groupby(["decade", "genre_bucket"])
        .size()
        .unstack(fill_value=0)
        .reindex(present_decades)
    )
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100

    fig, ax = plt.subplots(figsize=(13, 6))
    pivot_pct.plot(kind="bar", stacked=True, ax=ax, colormap="tab10", width=0.7)
    ax.set_title(f"Genre Share on Billboard Hot 100 by Decade (top {top_n} genres)")
    ax.set_xlabel("Decade")
    ax.set_ylabel("Share (%)")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    return fig


# ── 4. Artist country origins ─────────────────────────────────────────────────

def plot_country_origins(df: pd.DataFrame, top_n: int = 10) -> plt.Figure:
    """Horizontal bar chart of top artist countries on the Hot 100."""
    sub = df.dropna(subset=["mb_artist_country"])
    if sub.empty:
        raise ValueError("No artist country data. Check MusicBrainz enrichment.")

    counts = sub["mb_artist_country"].value_counts().head(top_n)
    fig, ax = plt.subplots(figsize=(9, 5))
    counts[::-1].plot(kind="barh", ax=ax, color=sns.color_palette("muted", top_n))
    ax.set_title(f"Top {top_n} Artist Countries on Billboard Hot 100 (all time)")
    ax.set_xlabel("Number of charting entries")
    fig.tight_layout()
    return fig


def plot_country_over_time(df: pd.DataFrame, top_countries: int = 5) -> plt.Figure:
    """Line chart of how country representation changed per decade."""
    sub = df.dropna(subset=["mb_artist_country", "decade"])
    present_decades = [d for d in DECADE_ORDER if d in sub["decade"].unique()]

    top = sub["mb_artist_country"].value_counts().head(top_countries).index.tolist()
    sub_top = sub[sub["mb_artist_country"].isin(top)]

    pivot = (
        sub_top.groupby(["decade", "mb_artist_country"])
        .size()
        .unstack(fill_value=0)
        .reindex(present_decades)
    )
    pivot_pct = pivot.div(sub.groupby("decade").size().reindex(present_decades), axis=0) * 100

    fig, ax = plt.subplots(figsize=(12, 5))
    for country in pivot_pct.columns:
        ax.plot(pivot_pct.index, pivot_pct[country], marker="o", label=country, linewidth=2)
    ax.set_title(f"Share of Hot 100 Entries by Artist Country (top {top_countries})")
    ax.set_ylabel("Share (%)")
    ax.set_xlabel("Decade")
    ax.legend()
    _rotate_xlabels(ax, "decade")
    fig.tight_layout()
    return fig


# ── 5. Chart longevity ─────────────────────────────────────────────────────────────

def plot_weeks_on_chart_over_time(df: pd.DataFrame) -> plt.Figure:
    """How long does a hit stay on the chart? Median weeks per decade."""
    sub = df.dropna(subset=["weeks_on_chart", "decade"])
    present_decades = [d for d in DECADE_ORDER if d in sub["decade"].unique()]

    medians = (
        sub.groupby("decade")["weeks_on_chart"]
        .median()
        .reindex(present_decades)
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(medians.index, medians.values, color=sns.color_palette("muted", len(medians)))
    ax.set_title("Median Weeks on Billboard Hot 100 by Decade")
    ax.set_ylabel("Weeks on chart (median)")
    ax.set_xlabel("Decade")
    _rotate_xlabels(ax, "decade")
    fig.tight_layout()
    return fig


# ── 6. Summary statistics ─────────────────────────────────────────────────────

def summary_by_decade(df: pd.DataFrame) -> pd.DataFrame:
    """Return a summary table of key metrics grouped by decade."""
    present_decades = [d for d in DECADE_ORDER if d in df.get("decade", pd.Series()).unique()]

    agg = {}
    if "duration_sec" in df.columns:
        agg["duration_sec"] = "median"
    if "weeks_on_chart" in df.columns:
        agg["weeks_on_chart"] = "median"
    if "title" in df.columns:
        agg["title"] = "count"

    if not agg:
        return pd.DataFrame()

    summary = df.groupby("decade").agg(agg).reindex(present_decades)
    summary.columns = [
        c.replace("_", " ").title() for c in summary.columns
    ]
    return summary.round(2)


# ── Utility ───────────────────────────────────────────────────────────────────

def _rotate_xlabels(ax: plt.Axes, by: str) -> None:
    if by == "year":
        ax.xaxis.set_major_locator(mticker.MultipleLocator(5))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
