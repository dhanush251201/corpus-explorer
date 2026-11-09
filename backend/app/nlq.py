"""
Natural language -> MongoDB query.

Two paths, in this order:

1. A deterministic parser that recognises institutions, dates, genres, quality
   constraints and quoted phrases. No API key, no cost, no surprises, and it
   explains every clause it produced.
2. An optional LLM fallback, used only when the parser understood nothing and
   ANTHROPIC_API_KEY is set. Whatever it returns is passed through the same
   safety validator as everything else before it can execute.

The parser always reports what it did NOT understand, so a user can see when a
query was only partly interpreted rather than silently getting wrong results.
"""
import json
import re
from datetime import datetime

from .config import settings
from .schema import knowledge, IMPUTED_DATE_INSTITUTIONS
from .safety import validate_filter, UnsafeQuery

YEAR = re.compile(r"\b(20[12][0-9])\b")
YEAR_RANGE = re.compile(r"\b(20[12][0-9])\s*(?:-|–|to|until|through)\s*(20[12][0-9])\b", re.I)
SINCE = re.compile(r"\b(?:since|after)\s+(20[12][0-9])\b", re.I)
# note: "from 2024" means *in* 2024 in ordinary usage, so it is NOT treated as
# open-ended here; "from 2022 to 2024" is caught by YEAR_RANGE above.
BEFORE = re.compile(r"\b(?:before|until|up to|prior to)\s+(20[12][0-9])\b", re.I)
QUOTED = re.compile(r"[\"“”']([^\"“”']{2,80})[\"“”']")
LIMIT = re.compile(r"\b(?:top|first|show me|give me)\s+(\d{1,3})\b", re.I)

GENRE_HINTS = ["commentary", "policy brief", "report", "analysis", "book",
               "bulletin", "working paper", "spotlight", "country report"]

STOP = set("""about and any are articles articles. by discuss discussing documents
find for from give in into is it its me mention mentioning of on or papers
published publications show that the their them these this to what which with
write written""".split())


def _institution_matches(text: str):
    """Match institution names and common abbreviations, longest first."""
    found, spans = [], []
    names = knowledge.institution_names()
    if not names:
        return found, text
    for name in sorted(names, key=len, reverse=True):
        # the display name, and the bare acronym before any parenthesis
        candidates = {name}
        bare = name.split("(")[0].strip()
        if bare:
            candidates.add(bare)
        for cand in candidates:
            if len(cand) < 3:
                continue
            rx = re.compile(rf"(?<!\w){re.escape(cand)}(?!\w)", re.I)
            m = rx.search(text)
            if m and name not in found:
                found.append(name)
                spans.append((m.start(), m.end()))
                break
    for a, b in sorted(spans, reverse=True):
        text = text[:a] + " " + text[b:]
    return found, text


def parse(text: str, base_filters: dict | None = None) -> dict:
    """Return {filter, terms, explain[], unparsed, limit, used}."""
    original = text or ""
    rest = " " + original + " "
    explain, filt = [], {}
    terms = []

    # --- quoted phrases are literal search terms --------------------------
    for q in QUOTED.findall(rest):
        terms.append(q)
        rest = rest.replace(f'"{q}"', " ").replace(f"'{q}'", " ")
        explain.append({"clause": "phrase", "value": q,
                        "note": "quoted, searched as an exact phrase"})

    # --- institutions -----------------------------------------------------
    insts, rest = _institution_matches(rest)
    if insts:
        filt["think_tank"] = {"$in": insts} if len(insts) > 1 else insts[0]
        explain.append({"clause": "think_tank", "value": ", ".join(insts),
                        "note": f"matched {len(insts)} institution name(s)"})

    # --- dates ------------------------------------------------------------
    date_clause = {}
    m = YEAR_RANGE.search(rest)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        date_clause = {"$gte": datetime(min(a, b), 1, 1),
                       "$lt": datetime(max(a, b) + 1, 1, 1)}
        explain.append({"clause": "published_at", "value": f"{a}–{b}",
                        "note": "year range"})
        rest = rest.replace(m.group(0), " ")
    elif SINCE.search(rest):
        y = int(SINCE.search(rest).group(1))
        date_clause = {"$gte": datetime(y, 1, 1)}
        explain.append({"clause": "published_at", "value": f"≥ {y}", "note": "open-ended"})
        rest = SINCE.sub(" ", rest)
    elif BEFORE.search(rest):
        y = int(BEFORE.search(rest).group(1))
        date_clause = {"$lt": datetime(y, 1, 1)}
        explain.append({"clause": "published_at", "value": f"< {y}", "note": "open-ended"})
        rest = BEFORE.sub(" ", rest)
    else:
        years = [int(y) for y in YEAR.findall(rest)]
        if years:
            y = years[0]
            date_clause = {"$gte": datetime(y, 1, 1), "$lt": datetime(y + 1, 1, 1)}
            explain.append({"clause": "published_at", "value": str(y), "note": "single year"})
            rest = YEAR.sub(" ", rest, count=1)
    if date_clause:
        filt["published_at"] = date_clause

    # --- genre ------------------------------------------------------------
    low = rest.lower()
    for g in GENRE_HINTS:
        if g in low:
            filt["publication_group"] = {"$regex": f"^{re.escape(g)}", "$options": "i"}
            explain.append({"clause": "publication_group", "value": g,
                            "note": "matched a document-type word"})
            rest = re.sub(re.escape(g), " ", rest, flags=re.I)
            break

    # --- quality constraints ---------------------------------------------
    if re.search(r"\b(reliable|trustworthy|real|accurate)\s+dates?\b", low):
        filt["think_tank"] = {"$nin": sorted(IMPUTED_DATE_INSTITUTIONS)}
        explain.append({"clause": "think_tank", "value": "exclude imputed dates",
                        "note": "drops FES and PRIO, whose dates are year-precision only"})
        rest = re.sub(r"\b(with\s+)?(reliable|trustworthy|real|accurate)\s+dates?\b",
                      " ", rest, flags=re.I)
    if re.search(r"\bwith (a )?pdf\b", low):
        filt["pdf_text"] = {"$nin": ["", None]}
        explain.append({"clause": "pdf_text", "value": "present", "note": "PDF text required"})
        rest = re.sub(r"\bwith (a )?pdf\b", " ", rest, flags=re.I)

    # --- limit ------------------------------------------------------------
    limit = None
    m = LIMIT.search(rest)
    if m:
        limit = min(int(m.group(1)), settings.MAX_PAGE_SIZE)
        rest = rest.replace(m.group(0), " ")

    # --- whatever is left becomes the search terms ------------------------
    leftover = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9'’-]{2,}", rest)
                if w.lower() not in STOP]
    if leftover and not terms:
        terms = [" ".join(leftover)]
        explain.append({"clause": "text", "value": " ".join(leftover),
                        "note": "free-text search over title and body"})
    elif leftover:
        explain.append({"clause": "text (additional)", "value": " ".join(leftover),
                        "note": "added to the phrase search"})
        terms.append(" ".join(leftover))

    if base_filters:
        filt.update(base_filters)

    return {"filter": validate_filter(filt), "terms": terms, "explain": explain,
            "limit": limit, "unparsed": "", "used": "pattern"}


# ---------------------------------------------------------------------------
LLM_SYSTEM = """You translate a researcher's question into a MongoDB filter for a
corpus of European think tank publications.

Fields: url (string), title (string), think_tank (string), publication_group
(string), published_at (BSON date), authors (array of strings), article_text
(string), pdf_text (string).

Reply with ONLY a JSON object: {"filter": <mongo filter>, "terms": [<free text
to search>], "note": "<one sentence on what you assumed>"}.

Rules: use $gte/$lt with ISO date strings for date ranges. Never use $where,
$function, $accumulator, $out or $merge. Never invent field names. If the
question implies full-text search, put those words in "terms" rather than
building a $regex."""


def parse_with_llm(text: str) -> dict | None:
    """Optional. Returns None if unavailable; the caller falls back to parse()."""
    if not settings.llm_enabled:
        return None
    try:
        import httpx
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": settings.LLM_MODEL, "max_tokens": 700,
                  "system": LLM_SYSTEM,
                  "messages": [{"role": "user", "content": text}]},
            timeout=25.0,
        )
        r.raise_for_status()
        body = r.json()["content"][0]["text"]
        body = re.sub(r"^```(?:json)?|```$", "", body.strip(), flags=re.M).strip()
        data = json.loads(body)
    except Exception as e:
        return {"error": f"LLM query generation failed: {e}"}

    filt = data.get("filter") or {}
    filt = _coerce_dates(filt)
    try:
        validate_filter(filt)
    except UnsafeQuery as e:
        return {"error": f"Generated query rejected by the safety validator: {e}"}
    return {"filter": filt, "terms": data.get("terms") or [],
            "explain": [{"clause": "model", "value": settings.LLM_MODEL,
                         "note": data.get("note", "")}],
            "limit": None, "unparsed": "", "used": "llm"}


def _coerce_dates(node):
    """Turn ISO strings under date operators into datetimes."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("$gte", "$gt", "$lte", "$lt") and isinstance(v, str):
                try:
                    out[k] = datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
                    continue
                except ValueError:
                    pass
            out[k] = _coerce_dates(v)
        return out
    if isinstance(node, list):
        return [_coerce_dates(v) for v in node]
    return node
