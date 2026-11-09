#!/usr/bin/env python3
"""
Where does the time actually go? Times each stage against the REAL cluster and
prints a breakdown, so optimisation targets what is slow rather than what looks
slow. Read-only, same as everything else.

    cd backend && python3 profile_perf.py
    python3 profile_perf.py --term "de-risking"
"""
import argparse, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings                     # noqa: E402
from app import db, search                          # noqa: E402
from app.schema import knowledge                    # noqa: E402


def timed(fn, runs=3):
    out = []
    for _ in range(runs):
        t = time.time()
        r = fn()
        out.append(time.time() - t)
    return min(out), statistics.median(out), r


def row(label, fn, runs=3, note=""):
    try:
        lo, med, r = timed(fn, runs)
    except Exception as e:
        print(f"  {label:<44} FAILED  {str(e)[:50]}")
        return None
    bar = "#" * min(40, int(med * 8))
    print(f"  {label:<44} {med*1000:7.0f}ms  (best {lo*1000:5.0f}) {bar} {note}")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term", default="strategic autonomy")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    if settings.DEMO_MODE:
        sys.exit("DEMO_MODE is on - unset it to profile the real cluster.")

    term = args.term
    master = settings.MASTER
    allc = search.scope_collections("all")
    print(f"\nProfiling {settings.DB_NAME} — {len(allc)} collections, term {term!r}\n")
    db.get_client()

    print("A. Primitives on one collection")
    row("estimated_document_count", lambda: db.estimated_count(master), 5)
    row("count_documents({})", lambda: db.count(master, {}), args.runs)
    clause, _ = search._text_clause([term], master, exact=False)
    row("count with $text (no regex confirm)", lambda: db.count(master, clause), args.runs)
    clause_x, _ = search._text_clause([term], master, exact=True)
    same = clause_x == clause
    row("count with $text + regex confirm", lambda: db.count(master, clause_x), args.runs,
        "(identical query - single word)" if same else "")

    print("\nB. Fetching 25 rows from one collection")
    light = {f: 1 for f in search.LIGHT_FIELDS}
    heavy = dict(light); heavy.update({"article_text": 1, "pdf_text": 1})
    row("metadata only  (phase 1)", lambda: db.find(master, clause, light, None, 0, 25), args.runs)
    row("with both text bodies (old way)", lambda: db.find(master, clause, heavy, None, 0, 25), args.runs)
    docs = db.find(master, clause, heavy, None, 0, 25)
    bytes_ = sum(len(d.get("article_text") or "") + len(d.get("pdf_text") or "") for d in docs)
    print(f"       -> those 25 documents carry {bytes_/1024:,.0f} KB of text; "
          f"across {len(allc)} collections that would be ~{bytes_*len(allc)/1024/1024:,.1f} MB per page")

    print("\nC. End-to-end search")
    row("one source", lambda: search.run("ECFR" if knowledge.collection_for("ECFR") else
                                         knowledge.institutions[0]["name"], [term], {}, "relevance", 0, 25),
        args.runs)
    row("all sources, relevance", lambda: search.run("all", [term], {}, "relevance", 0, 25), args.runs)
    row("all sources, newest", lambda: search.run("all", [term], {}, "newest", 0, 25), args.runs)
    row("all sources, browse (no term)", lambda: search.run("all", [], {}, "newest", 0, 25), args.runs)
    row("all sources, page 4", lambda: search.run("all", [term], {}, "relevance", 4, 25), args.runs)

    print("\nC2. Hydration path (phase 2)")
    light = db.find(master, clause, {f: 1 for f in search.LIGHT_FIELDS}, None, 0, 25)
    for d in light:
        d["_coll"] = master
    row("hydrate 25 rows", lambda: search._hydrate(light, [term], True), args.runs)
    mode = search.HYDRATE_PATH.get("mode")
    if mode == "projected":
        print("       -> snippets and word counts computed in the database (fast path)")
    else:
        print(f"       -> FELL BACK to fetching full documents: {search.HYDRATE_PATH.get('reason')}")
        print("          this is the difference between ~100ms and ~1300ms - worth investigating")

    print("\nD. Analysis endpoints")
    row("year_counts, one term, all sources",
        lambda: search.year_counts(allc, {}, [term]), 2)
    row("fetch_texts (concordance sample 100)",
        lambda: search.fetch_texts("all", [term], {}, cap=100), 2)

    print("\nE. Per-collection cost of the fan-out")
    times = []
    for c in allc:
        t = time.time(); db.count(c, clause); times.append((time.time() - t, c))
    times.sort(reverse=True)
    tot = sum(t for t, _ in times)
    print(f"  counting {term!r} in every collection: {tot*1000:.0f}ms serial, "
          f"~{tot/min(search.WORKERS, len(allc))*1000:.0f}ms with {search.WORKERS} workers")
    for t, c in times[:5]:
        print(f"       {t*1000:7.0f}ms  {c}")

    print("\nDone. The biggest number above is what to fix next.\n")


if __name__ == "__main__":
    main()
