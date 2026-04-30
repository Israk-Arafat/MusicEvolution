# Music Evolution — How Popular Music Has Changed Over Time

A data science project that tracks changes in popular music from 1958 to 2024 using the Billboard Hot 100 chart combined with metadata from the MusicBrainz API.

---

## What This Project Does

The pipeline downloads 66 years of Billboard Hot 100 chart history, enriches each song with musical metadata (duration, genre, country, label) from MusicBrainz, and produces a clean CSV dataset ready for analysis. A Jupyter notebook then answers questions like:

- Are streaming-era songs shorter than songs from the CD era?
- How has genre representation shifted across decades?
- Which countries produce the most charting artists?
- Do shorter songs reach higher chart positions?

---

## Project Structure

```
MusicEvolution/
├── main.py                  # Pipeline runner — builds the dataset
├── merge_caches.py          # Utility to combine caches from two machines
├── config.py                # Central settings (paths, thresholds)
├── requirements.txt         # Python dependencies
├── .env                     # Local overrides (optional, git-ignored)
├── .gitignore
│
├── src/
│   ├── billboard.py         # Billboard CSV loader + live scraper
│   ├── musicbrainz.py       # MusicBrainz API enrichment + caching
│   ├── merger.py            # Joins data, derives columns, saves CSV
│   ├── analysis.py          # Plot functions used by the notebook
│   └── __init__.py
│
├── notebooks/
│   └── analysis.ipynb       # Main analysis notebook (run this last)
│
└── data/                    # Created automatically, git-ignored
    ├── raw/
    │   └── billboard_hot100.csv     # Download from Kaggle (see below)
    ├── processed/
    │   └── merged_dataset.csv       # Output of main.py
    └── cache/
        └── musicbrainz_cache.json   # Persistent API cache
```

---

## Quick Start

### 1. Clone and set up the environment

```bash
git clone <repo-url>
cd MusicEvolution
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Download the Billboard dataset

Go to: https://www.kaggle.com/datasets/dhruvildave/billboard-the-hot-100-songs

Download `charts.csv` and save it as:

```
data/raw/billboard_hot100.csv
```

### 3. Build the dataset

```bash
python main.py
```

This runs all three pipeline steps and saves the result to `data/processed/merged_dataset.csv`. With ~31,000 unique songs and MusicBrainz's 1 request/second rate limit, a full run takes 8–10 hours. Progress is saved every 100 songs so you can interrupt and resume safely.

For a quick test with a small sample:

```bash
python main.py --limit 50
```

### 4. Open the notebook

```bash
jupyter notebook notebooks/analysis.ipynb
```

Run all cells from top to bottom.

---

## How the Pipeline Works

### Step 1 — Load Billboard data (`src/billboard.py`)

`load_billboard()` reads the Kaggle CSV and normalises the column names, since different versions of the dataset use different names for the same fields (e.g. `Current Week`, `rank`, `This Week` all mean the same thing).

The result is a DataFrame with one row per chart entry per week:

| Column             | Description                                     |
| ------------------ | ----------------------------------------------- |
| `chart_date`       | The week the song appeared (parsed to datetime) |
| `year` / `decade`  | Derived from chart_date                         |
| `rank`             | Chart position that week (1 = #1)               |
| `title` / `artist` | Song and performer                              |
| `peak_position`    | Highest position the song ever reached          |
| `weeks_on_chart`   | Cumulative weeks on the chart at that point     |
| `last_week`        | Previous week's position                        |

The full dataset has ~343,600 rows covering 1958–2024.

### Step 2 — Enrich with MusicBrainz (`src/musicbrainz.py`)

`MusicBrainzEnricher.enrich()` goes through every unique (title, artist) pair and looks it up on the MusicBrainz API. This adds five new columns:

| Column              | Description                              |
| ------------------- | ---------------------------------------- |
| `mb_duration_ms`    | Track length in milliseconds             |
| `mb_release_year`   | Earliest known release year              |
| `mb_genre_tags`     | Comma-separated crowd-sourced genre tags |
| `mb_artist_country` | Two-letter country code of the artist    |
| `mb_label`          | Record label                             |

**How matching works:**

1. Build a Lucene query: `recording:"Song Title" AND artist:"Artist Name"`
2. Send to MusicBrainz `search_recordings` (returns up to 5 candidates)
3. Score each candidate with fuzzy string matching using `rapidfuzz`:
   - Combined score = title similarity × 0.6 + artist similarity × 0.4
4. Accept the best match if it scores above 85 (configurable in `config.py`)
5. Fetch full detail for the winning match (releases, tags, artist info)

**Caching:** Every result (including "not found") is saved to `data/cache/musicbrainz_cache.json`. The pipeline checks the cache before making any API call, so rerunning `main.py` is fast after the first run.

**Rate limiting:** MusicBrainz requires a maximum of 1 request per second. The library enforces this automatically. The application must be registered with a name, version, and contact email (set in `config.py`).

**Retry logic:** Failed requests are retried up to 3 times with exponential backoff (2s, 4s, 8s) using the `tenacity` library.

**Query sanitisation:** Song titles that contain embedded quote characters (e.g. `"B" Girls`) are cleaned before the query is built to avoid breaking the Lucene query syntax.

### Step 3 — Finalize and save (`src/merger.py`)

`finalize()` adds derived columns and saves the result:

- `duration_sec` / `duration_min` — converted from `mb_duration_ms`
- `primary_genre` — first tag from `mb_genre_tags`
- `decade` — formatted as `1960s`, `1970s`, etc.

The final CSV is written to `data/processed/merged_dataset.csv`.

---

## The Analysis Notebook

`notebooks/analysis.ipynb` loads the merged CSV and walks through the full analysis in numbered sections.

### Section 1.5 — Data Preparation

Before analysis, two transformations are applied:

**Genre cleaning:** MusicBrainz tags are crowd-sourced and noisy. A `genre_map` dictionary maps raw tags to 10 broad categories (Rock, Pop, Hip-Hop/Rap, R&B/Soul, Country, Dance/Electronic, Latin, Jazz, Folk). Tags that don't match any keyword are discarded.

**Song-level deduplication:** The raw dataset has one row per chart appearance per week. A song that charts for 40 weeks has 40 rows. For analysis that should treat each song equally (genre, duration, country), a `song_level` DataFrame is created with one row per unique song, keeping each song's best rank, total weeks, and first appearance date.

### Section 2 — Summary by Decade

A summary table showing median duration, total songs, and top genres per decade.

### Section 3 — Song Duration Over Time

Line chart of median song duration by year and by decade. The 3-minute radio edit was an industry standard through the 1990s; streaming-era songs show a notable decline.

### Section 4 — Genre Shifts by Decade

Stacked bar chart using cleaned `broad_genre` labels at the song level. Shows the rise of Hip-Hop/Rap from the 1990s onwards and the decline of Rock's dominance.

### Section 5 — Country Origins

Horizontal bar chart of the top 10 artist countries (all time) and a line chart showing each country's share of the Hot 100 by decade. Both use song-level data so long-charting songs don't distort country counts.

### Section 6 — Chart Longevity

Median weeks on chart per decade. Streaming platforms allow songs to accumulate chart weeks far beyond what radio-era hits could, because streams count toward chart position long after a song's release.

### Section 7 — Are Streaming Songs Getting Shorter?

Songs are grouped into four eras:

| Era       | Years     |
| --------- | --------- |
| Pre-CD    | 1958–1981 |
| CD / MTV  | 1982–1999 |
| Download  | 2000–2014 |
| Streaming | 2015–2024 |

Box plots and median bars compare duration across eras. A **Mann-Whitney U test** gives a statistically rigorous p-value for whether the pre-streaming and streaming populations have different durations, making the finding more than just a visual impression.

### Section 8 — Genre vs Chart Longevity

A table and box plot answering: which genres produce songs that stay on the chart longest? Some genres that are less common overall may have much higher median chart weeks when they do appear.

### Section 9 — Peak Position vs Song Duration

A scatter plot with a regression line (y-axis inverted so #1 is at the top) showing whether shorter songs tend to peak higher. A duration bin table then shows median peak position and median weeks on chart broken into six length categories (`<2:30`, `2:30-3:00`, `3:00-3:30`, `3:30-4:00`, `4:00-5:00`, `5:00+`). Extreme outliers (below 60s or above 600s) are excluded from the scatter plot.

---

## Running on Two Machines (Speed-Up)

The MusicBrainz rate limit makes a full run slow (~8 hours for ~31,000 songs). You can split the work between two machines.

**Machine 1** (already running or starting fresh):

```bash
python main.py
# Uses: data/cache/musicbrainz_cache.json
# Processes songs A → Z
```

**Machine 2** (copy the project, then):

```bash
python main.py --reverse --cache-file data/cache/musicbrainz_cache_b.json
# Processes songs Z → A, writes to a separate cache file
```

**Merge the caches** (at any point, including mid-run):

```bash
# Copy Machine 2's cache to Machine 1
scp user@machine2:~/MusicEvolution/data/cache/musicbrainz_cache_b.json data/cache/

# Merge (Machine 1's entries take priority)
python merge_caches.py data/cache/musicbrainz_cache.json data/cache/musicbrainz_cache_b.json

# Run one final time — all cache hits, finishes in seconds
python main.py
```

Each machine writes to its own separate cache file, so there are no conflicts or corruption. Each independently respects MusicBrainz's 1 req/sec limit.

---

## Configuration

All settings live in `config.py`. You can override paths using a `.env` file.

| Setting           | Default                             | Description                                                      |
| ----------------- | ----------------------------------- | ---------------------------------------------------------------- |
| `BILLBOARD_CSV`   | `data/raw/billboard_hot100.csv`     | Path to the Kaggle CSV                                           |
| `MB_CACHE_FILE`   | `data/cache/musicbrainz_cache.json` | MusicBrainz cache path                                           |
| `MERGED_OUTPUT`   | `data/processed/merged_dataset.csv` | Final output path                                                |
| `FUZZY_THRESHOLD` | `85`                                | Minimum fuzzy match score (0–100) to accept a MusicBrainz result |
| `MB_CONTACT`      | `student@university.edu`            | Required by MusicBrainz ToS — change to your email               |

---

## Dependencies

| Library                       | Purpose                                     |
| ----------------------------- | ------------------------------------------- |
| `pandas`                      | Data loading, cleaning, and analysis        |
| `numpy`                       | Numeric operations                          |
| `scipy`                       | Mann-Whitney U statistical test             |
| `musicbrainzngs`              | MusicBrainz API client                      |
| `rapidfuzz`                   | Fuzzy string matching for song/artist names |
| `tenacity`                    | Retry logic for failed API calls            |
| `tqdm`                        | Progress bars                               |
| `requests` / `beautifulsoup4` | Live Billboard chart scraper                |
| `matplotlib` / `seaborn`      | Plots in the notebook                       |
| `plotly`                      | Interactive charts (optional)               |
| `python-dotenv`               | Load `.env` overrides                       |
| `jupyter` / `ipykernel`       | Notebook runtime                            |

---

## Data Notes

- **Coverage:** The Billboard dataset has 343,600 weekly chart entries. After deduplication there are approximately 31,000 unique songs.
- **MusicBrainz match rate:** Roughly 60–70% of songs get a duration match. Older or more obscure songs often have no MusicBrainz entry. Songs with no match still appear in the dataset with `NaN` in the `mb_*` columns.
- **Genre coverage:** Because MusicBrainz tags are crowd-sourced, coverage varies. Very old songs and one-hit wonders may have no genre tags at all.
- **One row per chart week:** The raw dataset intentionally keeps one row per song per week. This is the correct format for chart-presence analysis (longevity, rank trajectories). For song-level analysis, always use the `song_level` DataFrame created in the notebook.
