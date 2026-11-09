"""Text handling: coalescing, boilerplate removal, concordance, collocation."""
import re
from collections import Counter
from .schema import TEXT_FIELDS, TITLE_FIELDS, knowledge

WS = re.compile(r"\s+")
WORD = re.compile(r"[A-Za-zÀ-ÿĀ-ſ0-9'’-]+")

# Function words excluded from collocation output. Kept small and explicit -
# a linguist may well want to see "of" as a collocate, so this is a default,
# not a filter that is applied silently everywhere.
STOPWORDS = set("""
a an and are as at be been but by for from had has have he her his in is it its
of on or that the their they this to was were which who will with would you
""".split())


# An article_text below this is not a document - it is a stub. Roughly 250 KAS
# records, for instance, contain only the notice "is only available in German".
# Preferring such a stub over a real PDF rendering would be worse than useless.
ARTICLE_STUB_WORDS = 25

# Fields that hold the article as published on the web, in priority order.
ARTICLE_FIELDS = ["article_text", "full_text", "Full Text", "text"]
DOCUMENT_FIELDS = ["pdf_text"]


def text_variants(doc: dict) -> dict:
    """
    Every non-empty text field on this document with its size, keyed by a stable
    role name the UI can switch between:
        article  - the web article as published
        document - the full PDF rendering, which carries running headers,
                   page numbers and hyphenation that inflate any word count
    """
    out = {}
    for f in ARTICLE_FIELDS:
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            out["article"] = {"field": f, "words": word_count(v), "chars": len(v)}
            break
    for f in DOCUMENT_FIELDS:
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            out["document"] = {"field": f, "words": word_count(v), "chars": len(v)}
            break
    return out


def get_variant(doc: dict, role: str):
    fields = ARTICLE_FIELDS if role == "article" else DOCUMENT_FIELDS
    for f in fields:
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            return v, f
    return "", None


def pick_text(doc: dict, prefer: str = "article"):
    """
    Return (text, field, role).

    Prefers the web article over the PDF rendering, which is the change that
    makes word counts mean something: a PDF extraction of the same piece can run
    four times longer because of page furniture, so counting it overstates the
    document. Falls back to the PDF when the article is missing or is a stub -
    for FES, HCSS, IRIS and EUISS the PDF is the only real text there is.
    """
    order = ("article", "document") if prefer == "article" else ("document", "article")
    for role in order:
        text, field = get_variant(doc, role)
        if not text:
            continue
        if role == "article" and word_count(text) < ARTICLE_STUB_WORDS and prefer == "article":
            # a stub - only accept it if there is nothing else
            other, other_field = get_variant(doc, "document")
            if other:
                return other, other_field, "document"
        return text, field, role
    return "", None, None


def pick_title(doc: dict):
    for f in TITLE_FIELDS:
        v = doc.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "(untitled)"


def word_count(text: str) -> int:
    return len(WORD.findall(text or ""))


def strip_boilerplate(text: str, institution: str):
    """
    Remove the repeated opening phrases this institution's scraper leaked.
    Patterns come from the exploration pass, so they are derived from the data
    rather than guessed. Returns (cleaned, n_removed).
    """
    patterns = knowledge.boilerplate_for(institution)
    if not patterns or not text:
        return text, 0
    removed = 0
    head = text[:1200]
    tail = text[1200:]
    for p in patterns:
        if not p or len(p) < 8:
            continue
        rx = re.compile(re.escape(p).replace(r"\ ", r"\s+"), re.I)
        new = rx.sub(" ", head)
        if new != head:
            removed += 1
            head = new
    return WS.sub(" ", head).strip() + (" " + tail if tail else ""), removed


def snippet(text: str, terms, width: int = 260):
    """A short excerpt centred on the first matching term, with <mark> spans."""
    if not text:
        return ""
    plain = WS.sub(" ", text).strip()
    pos = -1
    for t in terms or []:
        m = re.search(re.escape(t), plain, re.I)
        if m:
            pos = m.start()
            break
    if pos < 0:
        out = plain[:width]
    else:
        a = max(0, pos - width // 3)
        out = ("…" if a else "") + plain[a:a + width]
    return highlight(out + ("…" if len(plain) > width else ""), terms)


def highlight(text: str, terms):
    for t in sorted(set(terms or []), key=len, reverse=True):
        if len(t) < 2:
            continue
        text = re.sub(f"({re.escape(t)})", r"<mark>\1</mark>", text, flags=re.I)
    return text


def kwic_lines(text: str, term: str, window: int = 8, limit: int = 25):
    """
    Keyword in context. Returns left context, the match, and right context as
    separate fields so the frontend can align them and sort by either side -
    which is how concordance reading actually works.
    """
    if not text or not term:
        return []
    words = WORD.findall(text)
    lowered = [w.lower() for w in words]
    parts = [p.lower() for p in WORD.findall(term)]
    if not parts:
        return []
    out = []
    n = len(parts)
    for i in range(len(lowered) - n + 1):
        if lowered[i:i + n] == parts:
            out.append({
                "left": " ".join(words[max(0, i - window):i]),
                "match": " ".join(words[i:i + n]),
                "right": " ".join(words[i + n:i + n + window]),
                "position": i,
            })
            if len(out) >= limit:
                break
    return out


def collocates(texts, term: str, window: int = 5, top: int = 40,
               drop_stopwords: bool = True):
    """
    Words co-occurring within +/- `window` tokens of the term, ranked by a
    simple log-ratio against their rate in the same documents overall. Raw
    frequency alone just returns the commonest words in the corpus.
    """
    parts = [p.lower() for p in WORD.findall(term)]
    if not parts:
        return []
    n = len(parts)
    near, overall = Counter(), Counter()
    hits = 0
    for text in texts:
        words = [w.lower() for w in WORD.findall(text or "")]
        overall.update(words)
        for i in range(len(words) - n + 1):
            if words[i:i + n] == parts:
                hits += 1
                lo, hi = max(0, i - window), min(len(words), i + n + window)
                for j in range(lo, hi):
                    if lo <= j < i or i + n <= j < hi:
                        near[words[j]] += 1
    if not hits:
        return []
    total_near = sum(near.values()) or 1
    total_all = sum(overall.values()) or 1
    rows = []
    for w, c in near.items():
        if drop_stopwords and w in STOPWORDS:
            continue
        if c < 2 or len(w) < 3:
            continue
        p_near = c / total_near
        p_all = max(overall.get(w, 1), 1) / total_all
        rows.append({"word": w, "near": c,
                     "corpus": overall.get(w, 0),
                     "score": round(p_near / p_all, 2)})
    rows.sort(key=lambda r: (-r["score"], -r["near"]))
    return {"occurrences": hits, "collocates": rows[:top]}
