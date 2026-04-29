"""
merge_caches.py — Merge two MusicBrainz cache files into one.

Usage
-----
After both machines have finished (or while one is still running, for a partial merge):

    python merge_caches.py data/cache/cache_a.json data/cache/cache_b.json

This writes the result into data/cache/musicbrainz_cache.json (the default path
that main.py reads). Then run `python main.py` one final time — it will be all
cache hits and finish in seconds.

You can safely run this while either machine is still going; entries already in
cache_a won't be overwritten by cache_b (cache_a takes priority).
"""
import json
import sys
from pathlib import Path

from config import MB_CACHE_FILE


def merge(path_a: Path, path_b: Path, output: Path = MB_CACHE_FILE) -> None:
    def load(p: Path) -> dict:
        if not p.exists():
            print(f"Warning: {p} not found — skipping")
            return {}
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded {len(data):,} entries from {p}")
        return data

    cache_a = load(path_a)
    cache_b = load(path_b)

    # cache_b fills gaps; cache_a entries take priority (they're from the
    # currently running machine and may be more recent)
    merged = {**cache_b, **cache_a}

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    only_in_b = len(set(cache_b) - set(cache_a))
    print(f"Merged: {len(merged):,} total entries ({only_in_b:,} new from cache_b)")
    print(f"Written to {output}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python merge_caches.py <cache_a.json> <cache_b.json>")
        sys.exit(1)
    merge(Path(sys.argv[1]), Path(sys.argv[2]))
