"""
Layer 3 of the read-only guarantee: structural validation of every filter and
pipeline before it reaches the driver.

Layer 1 is a MongoDB user holding only the `read` role (see README).
Layer 2 is that no write call exists anywhere in this codebase.
Layer 4 is the resource ceiling in config.py, applied in db.py.

This module is deliberately paranoid and deliberately dumb: it walks the whole
structure and refuses anything that could write, execute JavaScript, or reach
outside the configured database. It never tries to "fix" a query.
"""
from typing import Any

__all__ = ["UnsafeQuery", "validate_filter", "validate_pipeline", "assert_read_only"]


class UnsafeQuery(Exception):
    """Raised when a query contains something that is not a pure read."""


# Stages that write, execute code, or leak server state.
FORBIDDEN_STAGES = {
    "$out",            # writes a collection
    "$merge",          # writes a collection
    "$function",       # executes JavaScript
    "$accumulator",    # executes JavaScript
    "$where",          # executes JavaScript
    "$listLocalSessions", "$listSessions", "$currentOp", "$planCacheStats",
    "$collStats", "$indexStats", "$changeStream", "$changeStreamSplitLargeEvent",
    "$shardedDataDistribution", "$querySettings",
}

# Operators forbidden anywhere in a filter or expression tree.
FORBIDDEN_OPERATORS = {
    "$where", "$function", "$accumulator", "$expr_js",
}

# Stages that can name another collection or database. Allowed, but the target
# is checked against the configured database.
CROSS_COLLECTION_STAGES = {"$lookup", "$unionWith", "$graphLookup"}

MAX_DEPTH = 12


def _walk(node: Any, depth: int = 0) -> None:
    """Recursively reject forbidden operators anywhere in a structure."""
    if depth > MAX_DEPTH:
        raise UnsafeQuery(f"Query nests deeper than {MAX_DEPTH} levels")
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k in FORBIDDEN_OPERATORS:
                raise UnsafeQuery(f"Operator {k} is not permitted (executes code)")
            if isinstance(k, str) and k in FORBIDDEN_STAGES:
                raise UnsafeQuery(f"Stage {k} is not permitted (writes or leaks state)")
            _walk(v, depth + 1)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, depth + 1)


def validate_filter(filt: Any) -> dict:
    """Validate a find() filter. Returns it unchanged, or raises."""
    if filt is None:
        return {}
    if not isinstance(filt, dict):
        raise UnsafeQuery("Filter must be an object")
    _walk(filt)
    return filt


def _check_cross_collection(stage_name: str, body: Any, allowed_db: str) -> None:
    if not isinstance(body, dict):
        return
    # $lookup/$graphLookup name a collection in the SAME database - fine.
    # $unionWith and $lookup may carry an explicit db via `from: {db, coll}`.
    frm = body.get("from")
    if isinstance(frm, dict):
        target = frm.get("db")
        if target and target != allowed_db:
            raise UnsafeQuery(
                f"{stage_name} may not reach database '{target}'; "
                f"this deployment is scoped to '{allowed_db}'"
            )
    for nested in ("pipeline",):
        if nested in body:
            validate_pipeline(body[nested], allowed_db, _nested=True)


def validate_pipeline(pipeline: Any, allowed_db: str, max_stages: int = 24,
                      _nested: bool = False) -> list:
    """Validate an aggregation pipeline. Returns it unchanged, or raises."""
    if not isinstance(pipeline, list):
        raise UnsafeQuery("Pipeline must be a list of stages")
    if len(pipeline) > max_stages:
        raise UnsafeQuery(f"Pipeline has {len(pipeline)} stages; the limit is {max_stages}")

    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            raise UnsafeQuery("Each pipeline stage must be a single-key object")
        (name, body), = stage.items()
        if not isinstance(name, str) or not name.startswith("$"):
            raise UnsafeQuery(f"Invalid stage name: {name!r}")
        if name in FORBIDDEN_STAGES:
            raise UnsafeQuery(
                f"Stage {name} is not permitted. This application is read-only."
            )
        if name in CROSS_COLLECTION_STAGES:
            _check_cross_collection(name, body, allowed_db)
        _walk(body)
    return pipeline


def assert_read_only(roles: list) -> dict:
    """
    Inspect the roles the connected user actually holds and report whether any
    of them can write. Used at startup and surfaced in the UI - if someone
    points this app at an admin connection string, they should see that.
    """
    read_only_roles = {"read", "readAnyDatabase", "backup", "clusterMonitor",
                       "atlasAdmin_readOnly", "readOnly"}
    writable = []
    for r in roles or []:
        name = r.get("role") if isinstance(r, dict) else str(r)
        if name not in read_only_roles:
            writable.append(name)
    return {
        "roles": [r.get("role") if isinstance(r, dict) else str(r) for r in (roles or [])],
        "write_capable": bool(writable),
        "writable_roles": writable,
    }
