"""
What this application knows about the corpus.

These facts came out of the profiling work (profile_corpus.py and
insightsOfDatabase/) and are baked in deliberately: a user of this app should
not have to rediscover that FES's dates are fabricated or that half the corpus
keeps its text in a different field. Anything measured per-institution is
loaded from corpus_knowledge.json when available; the constants below are the
qualitative rules that JSON cannot express.
"""
import json
from pathlib import Path
from .config import settings

# Text fields in the order we prefer them. The corpus splits by institution:
# ~3,839 documents have content only in pdf_text, ~5,390 only in article_text.
# Never pick one field - always coalesce, and always report which was used.
TEXT_FIELDS = ["article_text", "pdf_text", "full_text", "Full Text", "text"]
TITLE_FIELDS = ["title", "Title", "cleaned_title"]

# Institutions whose published_at carries YEAR precision only; the month and
# day were fabricated at ingest. 3,144 documents, 15.9% of the corpus.
# Excluded automatically from month-level analysis.
IMPUTED_DATE_INSTITUTIONS = {"FES (Friedrich-Ebert-Stiftung)", "PRIO"}

# Every SWP document carries the same title - the scraper captured the site
# logo's alt text. Body text is fine.
BROKEN_TITLE_INSTITUTIONS = {"SWP"}
BROKEN_TITLE_MARKER = "Science and Politics Foundation"

# Institutions absent from top_40_think_tanks purely because their collection
# name lacks the `tanks.` prefix. 3,732 documents.
EXCLUDED_FROM_MASTER = {
    "Chatham House", "International Crisis Group",
    "International Institute for Strategic Studies", "Clingendael Institute",
    "HIIA", "GLOBSEC Policy Institute",
}

# Fields genuinely stored as BSON dates. `date_of_publication` is deliberately
# NOT here - it holds an ISO *string* in this corpus, so coercing it would break
# any filter on it.
DATE_FIELDS = {"published_at", "ingested_at"}

SHORT_TEXT_WORDS = 100          # below this it is probably not a document
DEFAULT_FIELDS = [
    "url", "title", "think_tank", "publication_group", "published_at",
    "authors", "source_file", "pdf_url",
]

SORTS = {
    "relevance":  None,                        # only valid with a text query
    "newest":     [("published_at", -1)],
    "oldest":     [("published_at", 1)],
    "longest":    [("_wordcount", -1)],        # computed, applied in-process
    "institution": [("think_tank", 1), ("published_at", -1)],
}


class Knowledge:
    """Per-institution facts, loaded from corpus_knowledge.json if present."""

    def __init__(self):
        self.institutions = []
        self.boilerplate = {}
        self.genres = []
        self.stopped_early = {}
        self.totals = {}
        self.coverage_months = {}
        self.loaded_from = None
        self._load()

    def _load(self):
        p = Path(settings.KNOWLEDGE_PATH)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
        except Exception:
            return
        self.institutions = data.get("institutions", [])
        self.boilerplate = data.get("boilerplate", {})
        self.genres = data.get("genres", [])
        self.stopped_early = data.get("stopped_early", {})
        self.totals = data.get("totals", {})
        self.coverage_months = data.get("coverage_months", {})
        self.loaded_from = str(p)

    # ---- lookups --------------------------------------------------------
    def collection_for(self, institution: str):
        for i in self.institutions:
            if i["name"] == institution:
                return i["collection"]
        return None

    def institution_names(self):
        return sorted(i["name"] for i in self.institutions)

    def info(self, institution: str):
        for i in self.institutions:
            if i["name"] == institution:
                return i
        return {}

    def boilerplate_for(self, institution: str):
        return self.boilerplate.get(institution, [])


knowledge = Knowledge()


def quality_flags(doc: dict, word_count: int, text_source: str,
                  has_article: bool | None = None) -> list:
    """
    Per-document warnings, derived from what the profiling found. These are
    shown on every search result so a user cannot silently build an analysis
    on a document with a fabricated date.
    """
    flags = []
    tank = doc.get("think_tank") or ""
    if tank in IMPUTED_DATE_INSTITUTIONS:
        flags.append({
            "id": "imputed_date", "severity": "critical",
            "label": "Date imputed",
            "detail": f"{tank} publication dates carry year precision only; "
                      "the month and day were fabricated at ingest. Safe for "
                      "year-level analysis, not for month-level.",
        })
    if tank in BROKEN_TITLE_INSTITUTIONS or BROKEN_TITLE_MARKER in (doc.get("title") or ""):
        flags.append({
            "id": "broken_title", "severity": "critical",
            "label": "Title unreliable",
            "detail": "All 614 SWP records share one title string taken from the "
                      "site logo. The body text is unaffected.",
        })
    if word_count and word_count < SHORT_TEXT_WORDS:
        flags.append({
            "id": "short_text", "severity": "warning",
            "label": f"Only {word_count} words",
            "detail": "Below the threshold where this is likely to be a real "
                      "publication. Often a staff page, stub or placeholder.",
        })
    # This flags the ABSENCE of a web article, not which text is on screen - a
    # reader who switches to the PDF view of a document that has both should not
    # be warned that no article exists.
    if has_article is None:
        has_article = bool((doc.get("article_text") or "").strip())
    if not has_article:
        flags.append({
            "id": "pdf_only", "severity": "info",
            "label": "PDF only",
            "detail": "No usable web text for this document, so the text shown is "
                      "extracted from the PDF and may carry running headers, page "
                      "numbers and hard line breaks.",
        })
    if tank in EXCLUDED_FROM_MASTER:
        flags.append({
            "id": "outside_master", "severity": "info",
            "label": "Outside master collection",
            "detail": f"{tank} is one of six institutions absent from "
                      "top_40_think_tanks because its collection name lacks the "
                      "`tanks.` prefix.",
        })
    return flags


def coerce_dates(node, inside_date_field: bool = False):
    """
    Turn ISO-8601 strings into datetimes underneath genuine date fields.

    JSON has no date type, so a filter arriving over HTTP carries
    {"published_at": {"$gte": "2024-01-01T00:00:00"}}. MongoDB compares BSON
    types before values, so a string never matches a date and the query returns
    nothing at all - silently, which is the worst kind of wrong.
    """
    from datetime import datetime
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in DATE_FIELDS:
                out[k] = coerce_dates(v, True)
            elif inside_date_field and isinstance(v, str):
                out[k] = _iso(v)
            else:
                out[k] = coerce_dates(v, inside_date_field)
        return out
    if isinstance(node, list):
        return [coerce_dates(v, inside_date_field) for v in node]
    if inside_date_field and isinstance(node, str):
        return _iso(node)
    return node


def _iso(v: str):
    from datetime import datetime
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return v
