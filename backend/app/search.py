"""Search orchestration: scope resolution, text strategy, result shaping."""
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import db
from .config import settings
from .schema import (knowledge, quality_flags, DEFAULT_FIELDS, SORTS,
                     EXCLUDED_FROM_MASTER, IMPUTED_DATE_INSTITUTIONS)
log = logging.getLogger("corpus.search")

from .textutil import (pick_text, pick_title, word_count, snippet,
                       strip_boilerplate, text_variants)

MERGE_CAP = 400          # per-collection ceiling when merging in-process
SNIPPET_SLICE = 1600     # chars fetched per text field, centred on the match
ANALYSIS_SLICE = 40000   # chars per document for concordance / collocation
WORKERS = 8              # the union scope touches 38 collections; serialising
                         # those round trips is what makes it feel broken


def parallel(fn, items):
    """
    Map `fn` across collections concurrently. PyMongo's client is thread-safe and
    pools connections, so this turns 38 sequential round trips into roughly one.
    Falls back to serial in demo mode, where the backing store is in-memory and
    concurrency buys nothing.
    """
    items = list(items)
    if settings.DEMO_MODE or len(items) < 2:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(items))) as pool:
        return list(pool.map(fn, items))


def scope_collections(scope: str) -> list:
    """
    'all' (default) -> every per-source collection in the database. Derived from
                       the database itself, so a stale knowledge file cannot
                       hide a source.
    'master'        -> top_40_think_tanks only; omits six sources and 3,732
                       documents, so it is never the default.
    <name>          -> that one source.
    """
    try:
        catalog = db.source_catalog()
    except Exception:
        catalog = [{"collection": i["collection"], "name": i["name"]}
                   for i in knowledge.institutions]
    names = [c["collection"] for c in catalog]
    if scope in (None, "", "all", "union"):
        return names or [settings.MASTER]
    if scope == "master":
        return [settings.MASTER]
    for c in catalog:
        if c["name"] == scope or c["collection"] == scope:
            return [c["collection"]]
    coll = knowledge.collection_for(scope)
    return [coll] if coll else (names or [settings.MASTER])


def phrase_regex(term: str) -> str:
    """
    A regex that matches the term as a phrase: flexible whitespace, tolerant of
    the hyphen in things like "de-risking" / "de risking", and bounded so
    "China" does not match inside "Chinatown".
    """
    esc = re.escape(term.strip())
    esc = esc.replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
    lead = r"\b" if term[:1].isalnum() else ""
    trail = r"\b" if term[-1:].isalnum() else ""
    return f"{lead}{esc}{trail}"


def _any_field(term: str) -> dict:
    rx = {"$regex": phrase_regex(term), "$options": "i"}
    return {"$or": [{"title": rx}, {"article_text": rx}, {"pdf_text": rx}]}


def _text_clause(terms, coll, exact: bool = True):
    """
    Build the text-matching part of a query.

    The subtlety that matters: MongoDB's $text treats an unquoted search string
    as a list of terms joined by OR, so {"$search": "strategic autonomy"} matches
    every document containing EITHER word - about half this corpus. Wrapping each
    term in literal double quotes turns it into a phrase search.

    With `exact` (the default) a regex confirmation is ANDed on top. The text
    index has already narrowed the candidate set by then, so this costs little
    and it removes the residual imprecision of stemming - which is what makes the
    app's counts agree with the figures in the corpus profile.
    """
    terms = [t for t in (terms or []) if t and t.strip()]
    if not terms:
        return None, False

    if db.capabilities(coll).get("text_index"):
        clause = {"$text": {"$search": " ".join(f'"{t}"' for t in terms)}}
        # The regex confirmation is only worth its cost for MULTI-WORD phrases.
        # For a single word the index is already exact (bar stemming), and the
        # regex would have to be evaluated against every candidate document's
        # full text - which for a common word means scanning thousands of
        # documents of up to 79,000 words each.
        needs_confirm = [t for t in terms if " " in t.strip() or "-" in t]
        if (exact and needs_confirm) or len(terms) > 1:
            clause["$and"] = [_any_field(t) for t in (needs_confirm or terms)]
        return clause, True

    # No text index on this collection - regex alone. All terms must appear.
    return {"$and": [_any_field(t) for t in terms]}, False


def _shape(doc, coll, terms, strip=True, counts=None):
    raw, field, role = pick_text(doc)
    tank = doc.get("think_tank") or coll.replace("tanks.", "").replace("_", " ")
    text = raw
    removed = 0
    if strip and raw:
        text, removed = strip_boilerplate(raw, tank)
    variants = text_variants(doc)
    if counts:
        # Word counts computed in the database over the FULL text. The text held
        # here is only a snippet window, so counting it locally would be wrong.
        for role, n in counts.items():
            if n and role in variants:
                variants[role]["words"] = n
            elif n:
                variants[role] = {"field": "article_text" if role == "article" else "pdf_text",
                                  "words": n, "chars": None}
        wc_role = "article" if variants.get("article", {}).get("words") else "document"
        role = wc_role if variants.get(wc_role) else role
    # The headline word count is the ARTICLE's, when there is one. A PDF
    # rendering of the same piece runs several times longer because of running
    # headers and page furniture, so counting that overstates the document.
    wc = (variants.get(role, {}) or {}).get("words") if counts else None
    if not wc:
        wc = word_count(text)
    return {
        "id": str(doc.get("_id")),
        "url": doc.get("url"),
        "title": pick_title(doc),
        "think_tank": tank,
        "publication_group": doc.get("publication_group"),
        "published_at": (doc.get("published_at").isoformat()
                         if isinstance(doc.get("published_at"), datetime) else doc.get("published_at")),
        "authors": doc.get("authors") or [],
        "word_count": wc,
        "text_role": role,
        "text_source": field,
        "variants": variants,
        "boilerplate_removed": removed,
        "pdf_url": doc.get("pdf_url") or None,
        "collection": coll,
        "snippet": snippet(text, terms),
        "flags": quality_flags(doc, wc, field, has_article="article" in variants),
        "score": doc.get("_score"),
    }


# Fields needed to rank, merge and page. Deliberately excludes the text bodies:
# fetching those for every candidate is what made "All sources" slow.
LIGHT_FIELDS = ["url", "title", "think_tank", "publication_group", "published_at",
                "authors", "source_file", "pdf_url"]


def run(scope="all", terms=None, filters=None, sort="relevance",
        page=0, size=25, strip=True, exact=True, min_words=None):
    """
    Two-phase.

    Phase 1 asks every collection in scope for METADATA ONLY - no article_text,
    no pdf_text - which is enough to count, rank, merge and page. Phase 2 then
    fetches the bodies for just the rows actually being shown.

    The previous single-phase version pulled 25 full documents from each of 38
    collections and discarded 925 of them: roughly 14 MB over the wire to render
    one page of 25 results.
    """
    terms = [t for t in (terms or []) if t and t.strip()]
    filters = dict(filters or {})
    colls = scope_collections(scope)
    size = max(1, min(int(size), settings.MAX_PAGE_SIZE))
    skip = max(0, int(page)) * size
    single = len(colls) == 1

    issued, total = [], 0
    use_score = any(_text_clause(terms, c, exact)[1] for c in colls) if terms else False

    def probe(coll):
        clause, is_text = _text_clause(terms, coll, exact)
        q = dict(filters)
        if clause:
            q.update(clause)
        try:
            n = db.count_cached(coll, q)
        except Exception:
            n = 0

        proj = {f: 1 for f in LIGHT_FIELDS}
        if is_text and sort == "relevance":
            proj["_score"] = {"$meta": "textScore"}
            order = [("_score", {"$meta": "textScore"})]
        else:
            order = SORTS.get(sort) or [("published_at", -1)]
            if order and order[0][0] == "_wordcount":
                order = [("published_at", -1)]

        want = size if single else min(MERGE_CAP, skip + size)
        try:
            docs = db.find(coll, q, proj, order, skip if single else 0, want,
                           ceiling=MERGE_CAP)
        except Exception:
            docs = db.find(coll, q, proj, None, skip if single else 0, want,
                           ceiling=MERGE_CAP)
        for d in docs:
            d["_coll"] = coll
        return coll, q, n, docs

    by_source, light = [], []
    for coll, q, n, docs in parallel(probe, colls):
        issued.append({"collection": coll, "filter": _jsonable(q)})
        total += n
        light += docs
        if n:
            by_source.append({"collection": coll,
                              "institution": _label_for(coll, docs),
                              "count": n})
    by_source.sort(key=lambda r: -r["count"])

    if not single:
        if sort == "relevance" and use_score:
            light.sort(key=lambda d: -(d.get("_score") or 0))
        elif sort == "oldest":
            light.sort(key=lambda d: d.get("published_at") or datetime.max)
        elif sort == "institution":
            light.sort(key=lambda d: (d.get("think_tank") or "",))
        else:
            light.sort(key=lambda d: d.get("published_at") or datetime.min, reverse=True)
        light = light[skip:skip + size]

    # ---- phase 2: bodies for the page only -------------------------------
    hits = _hydrate(light, terms, strip)

    post_filtered = False
    if min_words:
        before = len(hits)
        hits = [h for h in hits if (h.get("word_count") or 0) >= min_words]
        post_filtered = len(hits) != before
    if sort == "longest":
        hits.sort(key=lambda h: -(h.get("word_count") or 0))

    return {
        "total": total, "page": page, "size": size, "returned": len(hits),
        "hits": hits, "scope": scope, "collections": colls, "queries": issued,
        "by_source": by_source, "counts_approximate": post_filtered,
        "truncated_merge": not single and skip + size > MERGE_CAP,
    }


def _slice_expr(field, term, width):
    """
    A window of `field` centred on the first occurrence of `term`.

    $indexOfCP finds the match server-side and returns -1 when absent, so the
    $max clamps that to a slice from the start. This is what keeps hydration
    cheap: the snippet is cut in the database instead of shipping a 40,000-word
    document across the wire so Python can take 260 characters out of it.
    """
    base = {"$ifNull": [f"${field}", ""]}
    if not term:
        return {"$substrCP": [base, 0, width]}
    pos = {"$indexOfCP": [{"$toLower": base}, term.lower()]}
    start = {"$max": [0, {"$subtract": [pos, 200]}]}
    return {"$substrCP": [base, start, width]}


def _words_expr(field):
    """Exact word count computed server-side; guards the empty case, where
    $split would otherwise yield one element."""
    base = {"$ifNull": [f"${field}", ""]}
    return {"$cond": [{"$gt": [{"$strLenCP": base}, 0]},
                      {"$size": {"$split": [{"$trim": {"input": base}}, " "]}}, 0]}


HYDRATE_PATH = {"mode": "unknown", "reason": ""}


def _hydrate(light, terms, strip):
    """
    Phase 2. Fetches a snippet-sized window of each text field plus exact word
    counts, rather than the documents themselves. 25 rows used to arrive as
    ~1.3 MB of text; this makes it a few KB.
    """
    if not light:
        return []
    term = terms[0] if terms else None
    wanted = defaultdict(list)
    for d in light:
        wanted[d["_coll"]].append(d["_id"])

    project = {f: 1 for f in LIGHT_FIELDS}
    project.update({
        "article_text": _slice_expr("article_text", term, SNIPPET_SLICE),
        "pdf_text": _slice_expr("pdf_text", term, SNIPPET_SLICE),
        "_art_words": _words_expr("article_text"),
        "_pdf_words": _words_expr("pdf_text"),
    })

    def fetch(coll):
        try:
            rows = db.aggregate(coll, [{"$match": {"_id": {"$in": wanted[coll]}}},
                                       {"$project": project}])
            if HYDRATE_PATH["mode"] == "unknown":
                HYDRATE_PATH.update(mode="projected", reason="")
        except Exception as e:
            # Older servers, or a store without these operators: fall back to
            # fetching the bodies. Correct, just slower - and loudly reported,
            # because a silent fallback means no speedup and no signal.
            if HYDRATE_PATH["mode"] != "fallback":
                HYDRATE_PATH.update(mode="fallback", reason=str(e)[:160])
                log.warning("hydration fell back to fetching full documents: %s",
                            HYDRATE_PATH["reason"])
            proj = {f: 1 for f in LIGHT_FIELDS}
            proj.update({"article_text": 1, "pdf_text": 1})
            rows = db.find(coll, {"_id": {"$in": wanted[coll]}}, proj, None, 0,
                           len(wanted[coll]), ceiling=MERGE_CAP)
        return coll, rows

    full = {}
    for coll, rows in parallel(fetch, list(wanted)):
        for d in rows:
            full[(coll, str(d["_id"]))] = d

    out = []
    for d in light:
        coll = d["_coll"]
        body = full.get((coll, str(d["_id"]))) or d
        for k, v in d.items():
            body.setdefault(k, v)
        counts = None
        if "_art_words" in body or "_pdf_words" in body:
            counts = {"article": body.get("_art_words") or 0,
                      "document": body.get("_pdf_words") or 0}
        out.append(_shape(body, coll, terms, strip, counts))
    return out


def _label_for(coll, docs):
    for d in docs:
        if d.get("think_tank"):
            return d["think_tank"]
    for i in knowledge.institutions:
        if i["collection"] == coll:
            return i["name"]
    return coll.replace("tanks.", "").replace("_", " ")


def tank_label(coll, shaped):
    """Display name for a collection - from a document if we have one, else the
    knowledge file, else the collection name itself."""
    if shaped and shaped[0].get("think_tank"):
        return shaped[0]["think_tank"]
    for i in knowledge.institutions:
        if i["collection"] == coll:
            return i["name"]
    return coll.replace("tanks.", "").replace("_", " ")


def _jsonable(node):
    """Render a filter for display, turning datetimes into ISO strings."""
    if isinstance(node, dict):
        return {k: _jsonable(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_jsonable(v) for v in node]
    if isinstance(node, datetime):
        return node.isoformat()
    return node


def fetch_texts(scope, terms, filters, cap=300, exact=True):
    """
    Text for the analysis endpoints. Projects ONE coalesced field, capped, rather
    than both bodies in full - this endpoint was the slowest thing in the app at
    roughly 15 seconds for a 100-document sample.
    """
    colls = scope_collections(scope)
    per = max(20, cap // max(len(colls), 1))
    project = {"title": 1, "url": 1, "think_tank": 1, "published_at": 1,
               "text": {"$let": {
                   "vars": {"a": {"$ifNull": ["$article_text", ""]},
                            "p": {"$ifNull": ["$pdf_text", ""]}},
                   "in": {"$substrCP": [
                       {"$cond": [{"$gt": [{"$strLenCP": "$$a"}, 200]}, "$$a", "$$p"]},
                       0, ANALYSIS_SLICE]}}}}

    def one(coll):
        clause, _ = _text_clause(terms, coll, exact)
        q = dict(filters or {})
        if clause:
            q.update(clause)
        try:
            rows = db.aggregate(coll, [{"$match": q}, {"$limit": per},
                                       {"$project": project}])
        except Exception:
            proj = {"article_text": 1, "pdf_text": 1, "title": 1, "url": 1,
                    "think_tank": 1, "published_at": 1}
            rows = [{"text": pick_text(d)[0], "title": d.get("title"),
                     "url": d.get("url"), "think_tank": d.get("think_tank"),
                     "published_at": d.get("published_at")}
                    for d in db.find(coll, q, proj, None, 0, per, ceiling=cap)]
        out = []
        for d in rows:
            tank = d.get("think_tank") or coll
            text, _ = strip_boilerplate(d.get("text") or "", tank)
            out.append({"text": text, "title": pick_title(d), "url": d.get("url"),
                        "think_tank": tank,
                        "published_at": (d["published_at"].isoformat()
                                         if isinstance(d.get("published_at"), datetime) else None)})
        return out

    out = []
    for rows in parallel(one, colls):
        out += rows
    return out[:cap]


def year_counts(colls, base_filter, terms=None, years=(2022, 2023, 2024, 2025, 2026),
                exact=True):
    """
    Documents per year, as ONE aggregation per collection rather than one count
    per collection per year. On the union scope with four terms that is the
    difference between 38 queries and 760.
    """
    lo, hi = datetime(min(years), 1, 1), datetime(max(years) + 1, 1, 1)

    def one(coll):
        q = dict(base_filter or {})
        q["published_at"] = {"$gte": lo, "$lt": hi}
        if terms:
            clause, _ = _text_clause(terms, coll, exact)
            if clause:
                q.update(clause)
        try:
            rows = db.aggregate(coll, [
                {"$match": q},
                {"$group": {"_id": {"$dateToString": {"format": "%Y", "date": "$published_at"}},
                            "n": {"$sum": 1}}},
            ])
        except Exception:
            return {}
        return {int(r["_id"]): r["n"] for r in rows if r.get("_id")}

    totals = {y: 0 for y in years}
    for got in parallel(one, colls):
        for y, n in got.items():
            if y in totals:
                totals[y] += n
    return totals
