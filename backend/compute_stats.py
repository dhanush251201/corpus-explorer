#!/usr/bin/env python3
"""
Recompute the statistics snapshot. Reads the cluster, writes only the local
snapshot (STATS_PATH, data/stats.json by default) - nothing is ever written
back to MongoDB.

    python3 compute_stats.py            # recompute now
    python3 compute_stats.py --if-stale # only if older than the last Sunday

The application also recomputes weekly on its own (a daemon thread checks
hourly), so this is for driving the schedule externally, e.g. from cron:

    0 3 * * 0  cd /path/to/backend && ./.venv/bin/python compute_stats.py
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import stats                                  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-stale", action="store_true")
    ap.add_argument("--scope", default="all")
    args = ap.parse_args()

    current = stats.load()
    if args.if_stale and not stats.is_stale(current):
        print(f"snapshot from {current['generated']} is current - nothing to do")
        return

    print("computing (this scans every document; expect minutes)...")
    data = stats.refresh(args.scope)
    if data is None:
        sys.exit("another refresh is already running")
    t, l = data["totals"], data["length"]
    print(f"\n  {t['documents']:,} documents across {t['sources']} sources "
          f"in {data['duration_sec']}s")
    print(f"  {t['words_effective']:,} words · median {l['median']:,} · mean {l['mean']:,}")
    print(f"\n  longest : {l['longest'][0]['words']:,}w  {l['longest'][0]['source']} — "
          f"{l['longest'][0]['title'][:60]}")
    print(f"  shortest: {l['shortest'][0]['words']:,}w  {l['shortest'][0]['source']} — "
          f"{l['shortest'][0]['title'][:60]}")
    print(f"\n  written to {stats.SNAPSHOT}")
    if data.get("notes"):
        print("\n  notes:")
        for n in data["notes"]:
            print("   -", n)


if __name__ == "__main__":
    main()
