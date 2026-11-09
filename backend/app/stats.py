"""
Corpus statistics.

Computing these means counting every word in every document, which is far too
slow to do per request. So it runs on a schedule and the result is cached to
disk. The cluster is read-only, so the snapshot is written LOCALLY - to
STATS_PATH, data/stats.json by default - never back to MongoDB.

The heavy work happens in one aggregation per collection using $facet, so each
collection's text is scanned once and yields the summary, the extremes, the
per-year and per-type breakdowns and the author tallies together.
"""
import json
import logging
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .config import settings
from .schema import (knowledge, IMPUTED_DATE_INSTITUTIONS, BROKEN_TITLE_INSTITUTIONS,
                     EXCLUDED_FROM_MASTER)
from .textutil import word_count, pick_text, pick_title

log = logging.getLogger("corpus.stats")

SNAPSHOT = Path(settings.STATS_PATH)
ARTICLE_FLOOR = 25          # below this an article_text is a stub, not an article
SHORT_DOC = 100             # below this a document is probably not a publication
HIST_EDGES = [0, 1, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 10**9]

_state = {"running": False, "started": None, "error": None}
_lock = threading.Lock()


# --------------------------------------------------------------------------
def _words(field):
    base = {"$ifNull": [f"${field}", ""]}
    return {"$cond": [{"$gt": [{"$strLenCP": base}, 0]},
                      {"$size": {"$split": [{"$trim": {"input": base}}, " "]}}, 0]}


META = {"url": 1, "title": 1, "think_tank": 1, "published_at": 1,
        "publication_group": 1, "w": 1, "aw": 1, "pw": 1, "_id": 0}


def _pipeline():
    return [
        {"$project": {"url": 1, "title": 1, "think_tank": 1, "published_at": 1,
                      "publication_group": 1, "authors": 1,
                      "aw": _words("article_text"), "pw": _words("pdf_text")}},
        # The effective length is the ARTICLE's, falling back to the PDF when the
        # article is missing or a stub - the same rule the reader uses, so the
        # numbers here match what a user sees on a document.
        {"$addFields": {"w": {"$cond": [{"$gte": ["$aw", ARTICLE_FLOOR]}, "$aw",
                                        {"$max": ["$aw", "$pw"]}]}}},
        {"$facet": {
            "summary": [{"$group": {
                "_id": None,
                "n": {"$sum": 1},
                "words": {"$sum": "$w"},
                "art_words": {"$sum": "$aw"},
                "pdf_words": {"$sum": "$pw"},
                "empty": {"$sum": {"$cond": [{"$eq": ["$w", 0]}, 1, 0]}},
                "no_article": {"$sum": {"$cond": [{"$lt": ["$aw", ARTICLE_FLOOR]}, 1, 0]}},
                "no_pdf": {"$sum": {"$cond": [{"$eq": ["$pw", 0]}, 1, 0]}},
                "short": {"$sum": {"$cond": [{"$and": [{"$gt": ["$w", 0]},
                                                       {"$lt": ["$w", SHORT_DOC]}]}, 1, 0]}},
                "first": {"$min": "$published_at"},
                "last": {"$max": "$published_at"},
                "author_slots": {"$sum": {"$size": {"$ifNull": ["$authors", []]}}},
                "no_author": {"$sum": {"$cond": [
                    {"$eq": [{"$size": {"$ifNull": ["$authors", []]}}, 0]}, 1, 0]}},
                "ws": {"$push": "$w"},
            }}],
            "longest": [{"$sort": {"w": -1}}, {"$limit": 3}, {"$project": META}],
            "shortest": [{"$match": {"w": {"$gt": 0}}}, {"$sort": {"w": 1}},
                         {"$limit": 3}, {"$project": META}],
            "shortest_real": [{"$match": {"w": {"$gte": SHORT_DOC}}}, {"$sort": {"w": 1}},
                              {"$limit": 3}, {"$project": META}],
            "by_year": [{"$match": {"published_at": {"$type": "date"}}},
                        {"$group": {"_id": {"$dateToString": {"format": "%Y",
                                                              "date": "$published_at"}},
                                    "n": {"$sum": 1}, "words": {"$sum": "$w"}}}],
            "by_type": [{"$group": {"_id": "$publication_group", "n": {"$sum": 1}}}],
            "authors": [{"$unwind": "$authors"},
                        {"$group": {"_id": "$authors", "n": {"$sum": 1}}}],
        }},
    ]


def _fallback(coll):
    """For stores without the aggregation operators (demo mode). Small data only."""
    rows = db.find(coll, {}, None, None, 0, 500, ceiling=2000)
    out = {"summary": [{"n": 0, "words": 0, "art_words": 0, "pdf_words": 0, "empty": 0,
                        "no_article": 0, "no_pdf": 0, "short": 0, "first": None,
                        "last": None, "author_slots": 0, "no_author": 0, "ws": []}],
           "longest": [], "shortest": [], "shortest_real": [], "by_year": [],
           "by_type": [], "authors": []}
    s = out["summary"][0]
    years, types, auth, docs = {}, {}, {}, []
    for d in rows:
        aw = word_count(d.get("article_text") or "")
        pw = word_count(d.get("pdf_text") or "")
        w = aw if aw >= ARTICLE_FLOOR else max(aw, pw)
        s["n"] += 1; s["words"] += w; s["art_words"] += aw; s["pdf_words"] += pw
        s["ws"].append(w)
        if w == 0: s["empty"] += 1
        if aw < ARTICLE_FLOOR: s["no_article"] += 1
        if pw == 0: s["no_pdf"] += 1
        if 0 < w < SHORT_DOC: s["short"] += 1
        pa = d.get("published_at")
        if hasattr(pa, "year"):
            years[str(pa.year)] = years.get(str(pa.year), 0) + 1
            s["first"] = pa if not s["first"] else min(s["first"], pa)
            s["last"] = pa if not s["last"] else max(s["last"], pa)
        types[d.get("publication_group")] = types.get(d.get("publication_group"), 0) + 1
        a = d.get("authors") or []
        s["author_slots"] += len(a)
        if not a: s["no_author"] += 1
        for x in a: auth[x] = auth.get(x, 0) + 1
        docs.append({"url": d.get("url"), "title": pick_title(d),
                     "think_tank": d.get("think_tank"), "published_at": pa,
                     "publication_group": d.get("publication_group"),
                     "w": w, "aw": aw, "pw": pw})
    docs.sort(key=lambda x: -x["w"])
    out["longest"] = docs[:3]
    nz = [d for d in docs if d["w"] > 0]
    out["shortest"] = list(reversed(nz))[:3]
    out["shortest_real"] = list(reversed([d for d in docs if d["w"] >= SHORT_DOC]))[:3]
    out["by_year"] = [{"_id": k, "n": v, "words": 0} for k, v in years.items()]
    out["by_type"] = [{"_id": k, "n": v} for k, v in types.items()]
    out["authors"] = [{"_id": k, "n": v} for k, v in auth.items()]
    return out


def _doc(d, source):
    return {"title": (d.get("title") or "(untitled)")[:140],
            "url": d.get("url"),
            "source": d.get("think_tank") or source,
            "words": d.get("w", 0),
            "article_words": d.get("aw", 0),
            "pdf_words": d.get("pw", 0),
            "published_at": (d["published_at"].isoformat()[:10]
                             if hasattr(d.get("published_at"), "isoformat") else None),
            "publication_group": d.get("publication_group")}


# --------------------------------------------------------------------------
def compute(scope: str = "all") -> dict:
    from . import search
    t0 = time.time()
    colls = search.scope_collections(scope)
    by_coll = {c["collection"]: c["name"] for c in db.source_catalog()}

    def one(coll):
        try:
            res = db.aggregate(coll, _pipeline())
            return coll, (res[0] if res else None), None
        except Exception as e:
            try:
                return coll, _fallback(coll), f"fallback: {str(e)[:90]}"
            except Exception as e2:
                return coll, None, str(e2)[:120]

    sources, all_ws, authors = [], [], {}
    years, types = {}, {}
    longest, shortest, shortest_real = [], [], []
    tot = {k: 0 for k in ("n", "words", "art_words", "pdf_words", "empty",
                          "no_article", "no_pdf", "short", "author_slots", "no_author")}
    first = last = None
    notes = []

    for coll, r, note in search.parallel(one, colls):
        if note:
            notes.append(f"{coll}: {note}")
        if not r:
            continue
        name = by_coll.get(coll, coll)
        s = (r.get("summary") or [{}])[0] or {}
        if not s.get("n"):
            continue
        for k in tot:
            tot[k] += s.get(k) or 0
        ws = s.get("ws") or []
        all_ws += ws
        if s.get("first"):
            first = s["first"] if first is None else min(first, s["first"])
        if s.get("last"):
            last = s["last"] if last is None else max(last, s["last"])
        for y in r.get("by_year") or []:
            if y.get("_id"):
                years[y["_id"]] = years.get(y["_id"], 0) + y["n"]
        for t in r.get("by_type") or []:
            key = t.get("_id") or "(none)"
            types[key] = types.get(key, 0) + t["n"]
        for a in r.get("authors") or []:
            if a.get("_id"):
                nm = str(a["_id"]).strip()
                if nm:
                    authors[nm] = authors.get(nm, 0) + a["n"]
        longest += [_doc(d, name) for d in (r.get("longest") or [])]
        shortest += [_doc(d, name) for d in (r.get("shortest") or [])]
        shortest_real += [_doc(d, name) for d in (r.get("shortest_real") or [])]

        srt = sorted(ws)
        sources.append({
            "name": name, "collection": coll, "documents": s["n"],
            "words": s.get("words") or 0,
            "mean_words": round((s.get("words") or 0) / s["n"]),
            "median_words": srt[len(srt) // 2] if srt else 0,
            "max_words": srt[-1] if srt else 0,
            "empty": s.get("empty") or 0, "short": s.get("short") or 0,
            "no_article": s.get("no_article") or 0, "no_pdf": s.get("no_pdf") or 0,
            "first": s["first"].isoformat()[:10] if hasattr(s.get("first"), "isoformat") else None,
            "last": s["last"].isoformat()[:10] if hasattr(s.get("last"), "isoformat") else None,
            "imputed_dates": name in IMPUTED_DATE_INSTITUTIONS,
        })

    longest.sort(key=lambda d: -d["words"])
    shortest.sort(key=lambda d: d["words"])
    shortest_real.sort(key=lambda d: d["words"])
    sources.sort(key=lambda r: -r["documents"])
    srt = sorted(all_ws)

    def pct(p):
        return srt[min(len(srt) - 1, int(len(srt) * p))] if srt else 0

    hist = []
    for lo, hi in zip(HIST_EDGES, HIST_EDGES[1:]):
        n = sum(1 for w in srt if lo <= w < hi)
        hist.append({"from": lo, "to": (None if hi > 10 ** 8 else hi), "count": n})

    imputed = sum(r["documents"] for r in sources if r["imputed_dates"])
    broken = sum(r["documents"] for r in sources if r["name"] in BROKEN_TITLE_INSTITUTIONS)
    outside = sum(r["documents"] for r in sources if r["name"] in EXCLUDED_FROM_MASTER)

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "duration_sec": round(time.time() - t0, 1),
        "scope": scope,
        "notes": notes[:8],
        "totals": {
            "documents": tot["n"],
            "sources": len(sources),
            "words_effective": tot["words"],
            "words_article": tot["art_words"],
            "words_pdf": tot["pdf_words"],
            "distinct_authors": len(authors),
            "author_slots": tot["author_slots"],
            "mean_authors_per_doc": round(tot["author_slots"] / tot["n"], 2) if tot["n"] else 0,
            "documents_without_author": tot["no_author"],
            "first_published": first.isoformat()[:10] if hasattr(first, "isoformat") else None,
            "last_published": last.isoformat()[:10] if hasattr(last, "isoformat") else None,
        },
        "length": {
            "mean": round(tot["words"] / tot["n"]) if tot["n"] else 0,
            "median": pct(0.5), "p10": pct(0.10), "p90": pct(0.90), "p99": pct(0.99),
            "histogram": hist,
            "longest": longest[:10],
            "shortest": shortest[:10],
            "shortest_real": shortest_real[:10],
            "short_doc_threshold": SHORT_DOC,
        },
        "quality": {
            "empty_documents": tot["empty"],
            "short_documents": tot["short"],
            "no_article_text": tot["no_article"],
            "no_pdf_text": tot["no_pdf"],
            "imputed_dates": imputed,
            "broken_titles": broken,
            "outside_master": outside,
        },
        "by_year": dict(sorted(years.items())),
        "by_type": sorted([{"name": k, "documents": v} for k, v in types.items()],
                          key=lambda r: -r["documents"])[:25],
        "top_authors": sorted([{"name": k, "documents": v} for k, v in authors.items()],
                              key=lambda r: -r["documents"])[:25],
        "by_source": sources,
    }


# --------------------------------------------------------------------------
def load() -> dict | None:
    if SNAPSHOT.exists():
        try:
            return json.loads(SNAPSHOT.read_text())
        except Exception as e:
            log.warning("could not read stats snapshot: %s", e)
    return None


def save(data: dict):
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(data, indent=1, default=str))
    log.info("stats snapshot written to %s (%.1fs, %d documents)",
             SNAPSHOT, data.get("duration_sec", 0), data.get("totals", {}).get("documents", 0))


def last_sunday(now: datetime | None = None) -> datetime:
    """Most recent Sunday 03:00 local time, at or before `now`."""
    now = now or datetime.now()
    d = now.replace(hour=3, minute=0, second=0, microsecond=0)
    d -= timedelta(days=(d.weekday() + 1) % 7)       # Monday=0 ... Sunday=6
    if d > now:
        d -= timedelta(days=7)
    return d


def is_stale(data: dict | None) -> bool:
    if not data:
        return True
    try:
        gen = datetime.fromisoformat(data["generated"]).replace(tzinfo=None)
    except Exception:
        return True
    return gen < last_sunday()


def refresh(scope: str = "all", force: bool = False) -> dict | None:
    """Recompute and persist. Returns None if another run is already in flight."""
    with _lock:
        if _state["running"]:
            return None
        _state.update(running=True, started=datetime.now(timezone.utc).isoformat(), error=None)
    try:
        data = compute(scope)
        save(data)
        return data
    except Exception as e:
        log.exception("stats refresh failed")
        _state["error"] = str(e)[:200]
        raise
    finally:
        _state["running"] = False


def state() -> dict:
    return dict(_state)


def start_scheduler():
    """
    Recompute weekly. A daemon thread rather than cron, so the schedule travels
    with the app and works wherever it is deployed; see the README for a cron
    line if you would rather drive it externally.
    """
    def loop():
        while True:
            try:
                if is_stale(load()):
                    log.info("stats snapshot is stale - recomputing")
                    refresh()
            except Exception:
                pass
            time.sleep(3600)

    t = threading.Thread(target=loop, name="stats-scheduler", daemon=True)
    t.start()
    return t
