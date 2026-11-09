"""
Database access. This module is the ONLY place that talks to MongoDB, and it
exposes exactly four operations: find, aggregate, count and distinct.

No write operation of any kind appears in this file. That is layer 2 of the
read-only guarantee, and it is verifiable mechanically:

    grep -rE "insert_|update_|delete_|replace_one|bulk_write|drop\(|find_and_modify" backend/app/

returns nothing outside demo.py, which seeds an in-memory mongomock instance
and never touches a real server.
"""
import logging
from typing import Any, Optional

from .config import settings
from .safety import validate_filter, validate_pipeline, assert_read_only, UnsafeQuery

log = logging.getLogger("corpus.db")

_client = None
_privileges: dict = {"checked": False}
_capabilities: dict = {}


# ---------------------------------------------------------------------------
def get_client():
    global _client
    if _client is not None:
        return _client
    if settings.DEMO_MODE:
        import mongomock
        from .demo import seed
        _client = mongomock.MongoClient()
        seed(_client)
        log.warning("DEMO_MODE: using in-memory fixtures, not the real cluster")
        return _client
    if not settings.MONGO_URI:
        raise RuntimeError("MONGO_URI is not set. Copy .env.example to .env and fill it in.")
    from pymongo import MongoClient
    _client = MongoClient(
        settings.MONGO_URI,
        serverSelectionTimeoutMS=15000,
        socketTimeoutMS=settings.MAX_TIME_MS + 10000,
        appname="corpus-explorer-readonly",
    )
    _client.admin.command("ping")
    return _client


def get_db():
    return get_client()[settings.DB_NAME]


# ---------------------------------------------------------------------------
def privileges() -> dict:
    """
    Ask the server which roles this connection actually holds, so the UI can
    warn if someone pointed the app at a read-write user. Best effort: some
    deployments do not permit connectionStatus.
    """
    global _privileges
    if _privileges.get("checked"):
        return _privileges
    info = {"checked": True, "roles": [], "write_capable": None,
            "writable_roles": [], "note": ""}
    if settings.DEMO_MODE:
        info.update(write_capable=False, roles=["demo"],
                    note="Demo mode - no real connection.")
        _privileges = info
        return info
    try:
        st = get_client().admin.command("connectionStatus")
        roles = st.get("authInfo", {}).get("authenticatedUserRoles", [])
        info.update(assert_read_only(roles))
        if info["write_capable"]:
            info["note"] = ("This connection can WRITE. The application will not "
                            "issue writes, but you should switch to a user holding "
                            "only the `read` role.")
        else:
            info["note"] = "Connection holds read-only roles."
    except Exception as e:                                  # pragma: no cover
        info["note"] = f"Could not verify roles: {e}"
    _privileges = info
    return info


_expr_support = {}


def supports_length_expr() -> bool:
    """
    Can the backing store evaluate $strLenCP inside $expr? Real MongoDB has done
    since 3.4; mongomock (demo mode) has not implemented it. Probed once so the
    minimum-length filter can degrade to an in-process pass instead of erroring.
    """
    if "ok" in _expr_support:
        return _expr_support["ok"]
    try:
        get_db()[settings.MASTER].count_documents(
            {"$expr": {"$gte": [{"$strLenCP": {"$ifNull": ["$article_text", ""]}}, 0]}},
            limit=1)
        _expr_support["ok"] = True
    except Exception:
        _expr_support["ok"] = False
    return _expr_support["ok"]


def capabilities(coll_name: str) -> dict:
    """Does this collection have a text index? Determines the search strategy."""
    if coll_name in _capabilities:
        return _capabilities[coll_name]
    caps = {"text_index": False, "indexes": []}
    try:
        for ix in get_db()[coll_name].list_indexes():
            caps["indexes"].append(ix.get("name"))
            if "text" in str(ix.get("key", {})):
                caps["text_index"] = True
    except Exception:
        pass
    _capabilities[coll_name] = caps
    return caps


# ---------------------------------------------------------------------------
# The four permitted operations. Every one validates first and caps second.
# ---------------------------------------------------------------------------
def find(coll: str, filt: dict, projection: Optional[dict] = None,
         sort: Optional[list] = None, skip: int = 0, limit: int = 25,
         ceiling: Optional[int] = None) -> list:
    """
    `ceiling` raises the per-call row cap above MAX_PAGE_SIZE for internal
    callers that legitimately need more rows (cross-collection merging,
    concordance and collocation sampling). It is itself bounded by
    MAX_SCAN_DOCS, so no caller can ask for the whole corpus.
    """
    filt = validate_filter(filt)
    cap = settings.MAX_PAGE_SIZE if ceiling is None else min(int(ceiling), settings.MAX_SCAN_DOCS)
    skip = max(0, min(int(skip), settings.MAX_SKIP))
    limit = max(1, min(int(limit), cap))
    cur = get_db()[coll].find(filt, projection)
    if sort:
        cur = cur.sort(sort)
    cur = cur.skip(skip).limit(limit)
    try:
        cur = cur.max_time_ms(settings.MAX_TIME_MS)
    except Exception:
        pass                                   # mongomock has no max_time_ms
    return list(cur)


def aggregate(coll: str, pipeline: list) -> list:
    validate_pipeline(pipeline, settings.DB_NAME, settings.MAX_PIPELINE_STAGES)
    kwargs = {"allowDiskUse": True}
    try:
        return list(get_db()[coll].aggregate(pipeline,
                                             maxTimeMS=settings.MAX_TIME_MS, **kwargs))
    except TypeError:
        return list(get_db()[coll].aggregate(pipeline))     # mongomock
    except Exception as e:
        if "maxTimeMS" in str(e) or "allowDiskUse" in str(e):
            return list(get_db()[coll].aggregate(pipeline))
        raise


def count(coll: str, filt: dict) -> int:
    filt = validate_filter(filt)
    try:
        return get_db()[coll].count_documents(filt, maxTimeMS=settings.MAX_TIME_MS)
    except TypeError:
        return get_db()[coll].count_documents(filt)


def count_cached(coll: str, filt: dict, ttl: int = 300) -> int:
    """
    Counting a $text query costs the server real work - about half a second per
    collection on this corpus - and the same counts get asked for again on every
    page of the same search. The corpus is a frozen snapshot, so caching them is
    safe.
    """
    import hashlib, json
    key = "count:" + coll + ":" + hashlib.sha1(
        json.dumps(filt, sort_keys=True, default=str).encode()).hexdigest()
    return cached(key, ttl, lambda: count(coll, filt))


def distinct(coll: str, field: str, filt: Optional[dict] = None) -> list:
    filt = validate_filter(filt or {})
    if not isinstance(field, str) or field.startswith("$"):
        raise UnsafeQuery(f"Invalid field name: {field!r}")
    return get_db()[coll].distinct(field, filt)


_cache: dict = {}


def cached(key: str, ttl: int, producer):
    """
    Small in-process cache. The corpus is a frozen snapshot - every document
    carries the same ingested_at - so the source directory, the coverage grid
    and the facet lists cannot change between requests. Recomputing them per
    request was pure waste.
    """
    import time as _t
    hit = _cache.get(key)
    if hit and (_t.time() - hit[0]) < ttl:
        return hit[1]
    val = producer()
    _cache[key] = (_t.time(), val)
    return val


def clear_cache():
    _cache.clear()


def estimated_count(coll: str) -> int:
    """Collection size from metadata - O(1), versus a full evaluation."""
    try:
        return get_db()[coll].estimated_document_count()
    except Exception:
        return 0


def collections() -> list:
    return sorted(get_db().list_collection_names())


def source_catalog() -> list:
    """
    The authoritative list of sources: what is actually in the database, not
    what a metadata file claims. corpus_knowledge.json enriches these entries,
    but it never decides which sources exist - pointing the app at a stale or
    partial knowledge file used to silently hide collections.

    Returns [{collection, name}], display name resolved from the knowledge file,
    then from a document's think_tank field, then from the collection name.
    """
    def build():
        from .schema import knowledge
        by_coll = {i["collection"]: i["name"] for i in knowledge.institutions}
        out = []
        for coll in collections():
            if coll == settings.MASTER:
                continue
            name = by_coll.get(coll)
            if not name:
                try:
                    doc = get_db()[coll].find_one({"think_tank": {"$exists": True}},
                                                  {"think_tank": 1})
                    name = (doc or {}).get("think_tank")
                except Exception:
                    name = None
            out.append({"collection": coll,
                        "name": name or coll.replace("tanks.", "").replace("_", " ")})
        out.sort(key=lambda r: r["name"].lower())
        return out
    return cached("source_catalog", 900, build)


# ---------------------------------------------------------------------------
