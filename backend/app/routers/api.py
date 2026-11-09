"""HTTP surface. Every handler is a read; there are no POST-writes to Mongo."""
import csv, io, json, re
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db, nlq, search, stats
from ..config import settings
from ..safety import UnsafeQuery
from ..schema import (knowledge, IMPUTED_DATE_INSTITUTIONS, EXCLUDED_FROM_MASTER,
                      quality_flags, SORTS, coerce_dates)
from ..textutil import (pick_text, pick_title, kwic_lines, collocates,
                        strip_boilerplate, word_count, highlight,
                        text_variants, get_variant)

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ models
class SearchBody(BaseModel):
    q: str = ""
    scope: str = "all"
    terms: list[str] | None = None
    filters: dict | None = None
    sort: str = "relevance"
    page: int = 0
    size: int = 25
    strip_boilerplate: bool = True
    natural_language: bool = True
    use_llm: bool = False
    exact: bool = True      # phrase matching; off = broader, index-only matching
    min_words: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    author: str | None = None


class AnalyseBody(BaseModel):
    term: str
    scope: str = "all"
    filters: dict | None = None
    window: int = Field(8, ge=1, le=20)
    limit: int = Field(100, ge=1, le=400)
    sample: int = Field(120, ge=10, le=400)


# ------------------------------------------------------------------ meta
@router.get("/meta")
def meta():
    return db.cached("meta", 300, _meta)


def _meta():
    priv = db.privileges()
    return {
        "database": settings.DB_NAME,
        "master_collection": settings.MASTER,
        "demo_mode": settings.DEMO_MODE,
        "read_only": {
            "enforced": True,
            "layers": [
                "MongoDB user should hold only the `read` role (layer 1)",
                "No write call exists in the application (layer 2)",
                "Every filter and pipeline is structurally validated (layer 3)",
                "Time, row and depth ceilings on every query (layer 4)",
            ],
            "connection": priv,
        },
        "limits": {
            "max_page_size": settings.MAX_PAGE_SIZE,
            "max_time_ms": settings.MAX_TIME_MS,
            "max_skip": settings.MAX_SKIP,
            "max_export_rows": settings.MAX_EXPORT_ROWS,
        },
        "llm_available": settings.llm_enabled,
        "hydration": search.HYDRATE_PATH,
        "knowledge_loaded": knowledge.loaded_from,
        "knowledge_check": _knowledge_check(),
        "totals": knowledge.totals,
        "coverage_months": knowledge.coverage_months,
        "institutions": knowledge.institutions,
        "genres": knowledge.genres[:60],
        "sorts": list(SORTS),
        "caveats": [
            {"id": "imputed_dates", "severity": "critical",
             "title": "15.9% of publication dates are fabricated",
             "detail": "FES (2,968 documents) and PRIO (176) carry year precision "
                       "only; the month and day were invented at ingest. Exclude "
                       "them from any month-level analysis."},
            {"id": "split_text", "severity": "critical",
             "title": "Text lives in different fields per institution",
             "detail": "3,839 documents have content only in pdf_text and 5,390 "
                       "only in article_text. This app always coalesces and "
                       "reports which field it used."},
            {"id": "master_incomplete", "severity": "warning",
             "title": "The master collection is missing six institutions",
             "detail": "Chatham House, ICG, IISS, Clingendael, HIIA and GLOBSEC "
                       "(3,732 documents) are absent from top_40_think_tanks. "
                       "Switch scope to 'All institutions' to include them."},
            {"id": "broken_titles", "severity": "warning",
             "title": "All 614 SWP documents share one title",
             "detail": "The scraper captured the site logo's alt text. Body text "
                       "is unaffected; never deduplicate on title."},
        ],
    }


def _knowledge_check() -> dict:
    """
    Does the metadata file agree with the database about which sources exist?

    The source list is now derived from the database, so a mismatch no longer
    hides anything - but it does mean the enrichment (document counts, coverage
    dates, boilerplate patterns) is missing for some sources, and it usually
    means KNOWLEDGE_PATH is pointing at the demo fixture.
    """
    try:
        live = db.source_catalog()
    except Exception as e:
        return {"ok": None, "note": f"could not list collections: {e}"}
    known = {i["collection"] for i in knowledge.institutions}
    missing = [c["name"] for c in live if c["collection"] not in known]
    info = {"ok": not missing, "live_sources": len(live),
            "described_in_file": len(known), "undescribed": missing[:12],
            "file": knowledge.loaded_from}
    if missing:
        info["note"] = (f"{len(missing)} source(s) exist in the database but are not "
                        f"described in {knowledge.loaded_from or 'any knowledge file'}. "
                        "They are listed and searchable, but without document counts or "
                        "coverage dates. If KNOWLEDGE_PATH points at fixtures/, unset it.")
    else:
        info["note"] = "Metadata file matches the database."
    return info


@router.get("/health")
def health():
    try:
        db.get_client()
        return {"ok": True, "demo": settings.DEMO_MODE}
    except Exception as e:
        raise HTTPException(503, f"Database unreachable: {e}")


@router.get("/facets")
def facets(scope: str = "all"):
    return db.cached(f"facets:{scope}", 900, lambda: _facets(scope))


def _facets(scope: str = "all"):
    known = {i["collection"]: i for i in knowledge.institutions}
    catalog = db.source_catalog()
    insts = []
    for c in catalog:
        i = known.get(c["collection"], {})
        insts.append({"name": c["name"], "collection": c["collection"],
                      "docs": i.get("docs") or db.estimated_count(c["collection"]),
                      "in_master": c["collection"].startswith("tanks."),
                      "on_topic_pct": i.get("on_topic_pct"),
                      "imputed_dates": c["name"] in IMPUTED_DATE_INSTITUTIONS,
                      "outside_master": c["name"] in EXCLUDED_FROM_MASTER})
    return {
        "institutions": insts,
        "genres": [g["name"] for g in knowledge.genres[:60]],
        "years": [2022, 2023, 2024, 2025, 2026],
        "scopes": ([{"id": "all", "label": "All sources", "group": "",
                     "detail": f"{sum(i['docs'] for i in insts):,} documents across "
                               f"{len(insts)} sources"}]
                   + [{"id": i["name"], "label": i["name"], "group": "Individual sources",
                       "detail": f"{i['docs']:,} documents"}
                      for i in insts]
                   + [{"id": "master", "label": "top_40_think_tanks (partial)",
                       "group": "Legacy",
                       "detail": f"{knowledge.totals.get('master', '?'):,} documents — "
                                 "omits six institutions; kept for reference"}]),
    }


# ------------------------------------------------------------------ search
def _extra_filters(body: SearchBody) -> dict:
    """Filters the UI expresses as plain values rather than Mongo syntax."""
    from datetime import datetime as _dt
    f = {}
    if body.date_from or body.date_to:
        rng = {}
        if body.date_from:
            rng["$gte"] = _dt.fromisoformat(body.date_from)
        if body.date_to:
            rng["$lt"] = _dt.fromisoformat(body.date_to)
        f["published_at"] = rng
    if body.author:
        f["authors"] = {"$regex": re.escape(body.author), "$options": "i"}
    if body.min_words and db.supports_length_expr():
        # Word counts are not stored, so length is evaluated server-side on
        # whichever text field is longer. Characters per word varies, so the UI
        # presents this as approximate. Where the store cannot evaluate
        # $strLenCP (demo mode), search.run filters in-process instead.
        chars = int(body.min_words) * 6
        f["$expr"] = {"$gte": [
            {"$max": [{"$strLenCP": {"$ifNull": ["$article_text", ""]}},
                      {"$strLenCP": {"$ifNull": ["$pdf_text", ""]}}]}, chars]}
    return f


def _build(body: SearchBody):
    # JSON carries dates as strings; convert before they reach the driver.
    filters = coerce_dates(dict(body.filters or {}))
    filters.update(_extra_filters(body))
    terms = list(body.terms or [])
    explain = []
    used = "structured"
    if body.q and body.natural_language:
        parsed = None
        if body.use_llm and settings.llm_enabled:
            parsed = nlq.parse_with_llm(body.q)
            if parsed and parsed.get("error"):
                explain.append({"clause": "llm", "value": "failed",
                                "note": parsed["error"]})
                parsed = None
        if parsed is None:
            parsed = nlq.parse(body.q)
        used = parsed["used"]
        for k, v in parsed["filter"].items():
            filters.setdefault(k, v)
        terms += parsed["terms"]
        explain += parsed["explain"]
    elif body.q:
        terms.append(body.q)
    return filters, terms, explain, used


@router.post("/search")
def do_search(body: SearchBody):
    try:
        filters, terms, explain, used = _build(body)
        res = search.run(body.scope, terms, filters, body.sort,
                         body.page, body.size, body.strip_boilerplate, body.exact,
                         min_words=(body.min_words if body.min_words
                                    and not db.supports_length_expr() else None))
    except UnsafeQuery as e:
        raise HTTPException(400, f"Query rejected: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))
    res["interpretation"] = {"used": used, "terms": terms, "explain": explain}
    return res


@router.get("/document")
def document(url: str, scope: str = "all", strip: bool = True,
             role: str = Query("auto", pattern="^(auto|article|document)$")):
    """
    One document. `role` picks which text to return: the web article, the full
    PDF rendering, or whichever the app would choose by default. Both are always
    described in `variants`, so the UI can offer the switch only when there is
    something to switch between.
    """
    colls = search.scope_collections(scope)
    for coll in colls:
        docs = db.find(coll, {"url": url}, None, None, 0, 1)
        if not docs:
            continue
        d = docs[0]
        tank = d.get("think_tank") or coll
        variants = text_variants(d)
        if role in ("article", "document") and role in variants:
            raw, field = get_variant(d, role)
            chosen = role
        else:
            raw, field, chosen = pick_text(d)
        text, removed = strip_boilerplate(raw, tank) if strip else (raw, 0)
        return {
            "url": d.get("url"), "title": pick_title(d), "think_tank": tank,
            "publication_group": d.get("publication_group"),
            "authors": d.get("authors") or [],
            "published_at": (d["published_at"].isoformat()
                             if isinstance(d.get("published_at"), datetime) else d.get("published_at")),
            "pdf_url": d.get("pdf_url") or None,
            "source_file": d.get("source_file"),
            "collection": coll,
            "text": text, "raw_text": raw,
            "text_role": chosen, "text_source": field,
            "variants": variants,
            "boilerplate_removed": removed,
            "word_count": word_count(text),
            "flags": quality_flags(d, word_count(text), field,
                                   has_article="article" in variants),
        }
    raise HTTPException(404, "Document not found in this scope")


@router.get("/document/text")
def document_text(url: str, scope: str = "all", strip: bool = True,
                  role: str = Query("auto", pattern="^(auto|article|document)$")):
    """Plain-text download of a single document."""
    d = document(url, scope, strip, role)
    head = (f"{d['title']}\n{d['think_tank']}"
            f"{' · ' + d['published_at'][:10] if d.get('published_at') else ''}\n"
            f"{d['url']}\n"
            f"[text: {d['text_role']} ({d['text_source']}), "
            f"{d['word_count']:,} words]\n\n{'-' * 72}\n\n")
    name = re.sub(r"[^A-Za-z0-9]+", "_", (d["title"] or "document"))[:60] or "document"
    return StreamingResponse(
        io.BytesIO((head + (d["text"] or "")).encode("utf-8")),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.txt"'})


@router.get("/sources")
def sources():
    return db.cached("sources", 900, _sources)


def _sources():
    """
    Directory of every source: how many documents, what date range they cover,
    and which text fields they actually carry. This is the answer to "what is in
    here", which is the first question anyone opens the tool with.
    """
    out = []
    for i in knowledge.institutions:
        coll = i["collection"]
        # estimated_document_count reads collection metadata instead of
        # evaluating a query - the difference across 38 collections is seconds.
        n = db.estimated_count(coll) or i.get("docs", 0)
        out.append({
            "name": i["name"], "collection": coll, "documents": n,
            "in_master": i.get("in_master"),
            "article_pct": i.get("article_pct"),
            "pdf_pct": i.get("pdf_pct"),
            "first": i.get("first"), "last": i.get("last"),
            "imputed_dates": i["name"] in IMPUTED_DATE_INSTITUTIONS,
            "outside_master": i["name"] in EXCLUDED_FROM_MASTER,
            "broken_titles": i["name"] in {"SWP"},
            "stopped_early": knowledge.stopped_early.get(i["name"]),
        })
    out.sort(key=lambda r: -r["documents"])
    return {"sources": out, "total": sum(r["documents"] for r in out),
            "coverage_months": knowledge.coverage_months}


# ------------------------------------------------------------------ analysis
@router.post("/kwic")
def kwic(body: AnalyseBody):
    docs = search.fetch_texts(body.scope, [body.term], coerce_dates(body.filters or {}), cap=body.sample)
    lines, seen = [], 0
    for d in docs:
        for ln in kwic_lines(d["text"], body.term, body.window, limit=6):
            ln.update(title=d["title"], url=d["url"], think_tank=d["think_tank"],
                      published_at=d["published_at"])
            lines.append(ln)
            if len(lines) >= body.limit:
                break
        seen += 1
        if len(lines) >= body.limit:
            break
    return {"term": body.term, "documents_scanned": seen,
            "lines": lines, "truncated": len(lines) >= body.limit}


@router.post("/collocations")
def collocations(body: AnalyseBody):
    docs = search.fetch_texts(body.scope, [body.term], coerce_dates(body.filters or {}), cap=body.sample)
    res = collocates([d["text"] for d in docs], body.term, window=min(body.window, 10))
    if not res:
        return {"term": body.term, "occurrences": 0, "collocates": [],
                "documents_scanned": len(docs)}
    res.update(term=body.term, documents_scanned=len(docs))
    return res


class TrendBody(BaseModel):
    terms: list[str]
    scope: str = "all"
    exclude_imputed: bool = True
    exact: bool = True


@router.post("/trends")
def trends(body: TrendBody):
    key = f"trends:{body.scope}:{body.exclude_imputed}:{body.exact}:{'|'.join(body.terms)}"
    return db.cached(key, 900, lambda: _trends(body))


def _trends(body: TrendBody):
    """
    Rate per 1,000 documents per year. Annual output is not flat, so raw counts
    mislead; this normalises. Institutions with fabricated dates are excluded by
    default because they distort any within-year comparison.

    One aggregation per collection per term, not one count per year per term -
    on the union scope that is 38 queries instead of 760.
    """
    base = {}
    if body.exclude_imputed:
        base["think_tank"] = {"$nin": sorted(IMPUTED_DATE_INSTITUTIONS)}
    years = [2022, 2023, 2024, 2025, 2026]
    colls = search.scope_collections(body.scope)

    denom = search.year_counts(colls, base, None, years)

    series = []
    for term in body.terms[:6]:
        got = search.year_counts(colls, base, [term], years, exact=body.exact)
        counts = [got.get(y, 0) for y in years]
        rates = [round(1000 * c / denom[y], 1) if denom.get(y) else 0.0
                 for c, y in zip(counts, years)]
        series.append({"term": term, "rates": rates, "counts": counts,
                       "total": sum(counts)})

    return {"years": years, "denominator": [denom.get(y, 0) for y in years],
            "series": series, "excluded_imputed": body.exclude_imputed,
            "note": ("FES and PRIO excluded - their dates carry year precision only"
                     if body.exclude_imputed else
                     "Includes institutions whose dates were imputed")}


@router.get("/coverage")
def coverage(scope: str = "all"):
    return db.cached(f"coverage:{scope}", 900, lambda: _coverage(scope))


def _coverage(scope: str = "all"):
    """Documents per institution per month - the shape that reveals scraper gaps."""
    colls = search.scope_collections(scope)
    grid, months = {}, set()

    def one(coll):
        try:
            return coll, db.aggregate(coll, [
                {"$match": {"published_at": {"$type": "date"}}},
                {"$group": {"_id": {"tt": "$think_tank",
                                    "ym": {"$dateToString": {"format": "%Y-%m",
                                                             "date": "$published_at"}}},
                            "n": {"$sum": 1}}},
            ])
        except Exception:
            return coll, []

    for coll, rows in search.parallel(one, colls):
        for r in rows:
            tt = r["_id"].get("tt") or coll.replace("tanks.", "").replace("_", " ")
            ym = r["_id"].get("ym")
            if not ym:
                continue
            months.add(ym)
            grid.setdefault(tt, {})[ym] = r["n"]
    ms = sorted(months)
    return {
        "months": ms,
        "rows": [{"institution": k,
                  "counts": [grid[k].get(m, 0) for m in ms],
                  "total": sum(grid[k].values()),
                  "imputed_dates": k in IMPUTED_DATE_INSTITUTIONS}
                 for k in sorted(grid, key=lambda x: -sum(grid[x].values()))],
    }


# ------------------------------------------------------------------ stats
@router.get("/stats")
def get_stats(compute_if_missing: bool = True):
    """
    The weekly statistics snapshot. Counting every word in the corpus takes
    minutes, so this is precomputed and cached to local disk - never written
    back to MongoDB, which this application only ever reads.
    """
    data = stats.load()
    if data is None and compute_if_missing and not stats.state()["running"]:
        import threading
        threading.Thread(target=stats.refresh, daemon=True).start()
    st = stats.state()
    return {
        "snapshot": data,
        "stale": stats.is_stale(data),
        "running": st["running"],
        "started": st["started"],
        "error": st["error"],
        "next_refresh_after": (stats.last_sunday() + __import__("datetime").timedelta(days=7)).isoformat(),
        "storage": str(stats.SNAPSHOT),
    }


@router.post("/stats/refresh")
def refresh_stats():
    """
    Recompute now, in the background. This reads the cluster and writes only to
    the local snapshot file.
    """
    if stats.state()["running"]:
        return {"started": False, "reason": "a refresh is already running",
                "state": stats.state()}
    import threading
    threading.Thread(target=stats.refresh, daemon=True).start()
    return {"started": True, "state": stats.state()}


# ------------------------------------------------------------------ export
@router.post("/export")
def export(body: SearchBody, fmt: str = Query("csv", pattern="^(csv|json)$")):
    filters, terms, explain, used = _build(body)
    rows, page = [], 0
    while len(rows) < settings.MAX_EXPORT_ROWS:
        res = search.run(body.scope, terms, filters, body.sort, page,
                         settings.MAX_PAGE_SIZE, body.strip_boilerplate, body.exact)
        if not res["hits"]:
            break
        rows += res["hits"]
        page += 1
        if res["returned"] < settings.MAX_PAGE_SIZE or page > 60:
            break
    rows = rows[: settings.MAX_EXPORT_ROWS]

    if fmt == "json":
        payload = {"query": {"q": body.q, "scope": body.scope, "filters": search._jsonable(filters),
                             "terms": terms, "interpretation": explain},
                   "exported": len(rows), "rows": rows}
        return StreamingResponse(io.BytesIO(json.dumps(payload, indent=1).encode()),
                                 media_type="application/json",
                                 headers={"Content-Disposition": "attachment; filename=corpus_export.json"})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["url", "title", "think_tank", "publication_group", "published_at",
                "authors", "word_count", "text_source", "flags"])
    for r in rows:
        w.writerow([r["url"], r["title"], r["think_tank"], r["publication_group"],
                    r["published_at"], "; ".join(r["authors"]), r["word_count"],
                    r["text_source"], "; ".join(f["id"] for f in r["flags"])])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=corpus_export.csv"})
