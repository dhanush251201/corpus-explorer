"""
The read-only guarantee is the point of this application, so it gets the tests.
Run:  cd backend && python3 -m pytest tests/ -q
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from app.safety import validate_filter, validate_pipeline, assert_read_only, UnsafeQuery

DB = "Top40ThinkTanks"

HOSTILE_PIPELINES = [
    [{"$out": "stolen"}],
    [{"$merge": {"into": "victim"}}],
    [{"$match": {"$where": "sleep(5000)"}}],
    [{"$project": {"x": {"$function": {"body": "function(){}", "args": [], "lang": "js"}}}}],
    [{"$group": {"_id": None, "x": {"$accumulator": {"init": "f", "lang": "js"}}}}],
    [{"$match": {}}, {"$out": {"db": "other", "coll": "c"}}],
    [{"$unionWith": {"from": {"db": "admin", "coll": "system.users"}}}],
    [{"$lookup": {"from": {"db": "other", "coll": "x"}, "as": "y"}}],
    [{"$collStats": {}}],
    [{"$currentOp": {}}],
]

HOSTILE_FILTERS = [
    {"$where": "this.x == 1"},
    {"a": {"$function": {"body": "f", "args": [], "lang": "js"}}},
    {"$and": [{"$or": [{"$where": "1"}]}]},              # buried deep
]

SAFE_PIPELINES = [
    [{"$match": {"think_tank": "ECFR"}}, {"$limit": 10}],
    [{"$match": {}}, {"$group": {"_id": "$think_tank", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}],
    [{"$unionWith": {"coll": "tanks.ECFR"}}],             # same database - allowed
    [{"$lookup": {"from": "tanks.SWP", "localField": "url",
                  "foreignField": "url", "as": "m"}}],
]


@pytest.mark.parametrize("p", HOSTILE_PIPELINES)
def test_hostile_pipelines_rejected(p):
    with pytest.raises(UnsafeQuery):
        validate_pipeline(p, DB)


@pytest.mark.parametrize("f", HOSTILE_FILTERS)
def test_hostile_filters_rejected(f):
    with pytest.raises(UnsafeQuery):
        validate_filter(f)


@pytest.mark.parametrize("p", SAFE_PIPELINES)
def test_safe_pipelines_pass(p):
    assert validate_pipeline(p, DB) == p


def test_stage_limit():
    with pytest.raises(UnsafeQuery):
        validate_pipeline([{"$match": {}}] * 40, DB, max_stages=24)


def test_depth_limit():
    node = {"a": 1}
    for _ in range(25):
        node = {"$and": [node]}
    with pytest.raises(UnsafeQuery):
        validate_filter(node)


def test_malformed_stages():
    for bad in [[{"$match": {}, "$limit": 1}], ["$match"], [{"match": {}}], "nope"]:
        with pytest.raises(UnsafeQuery):
            validate_pipeline(bad, DB)


def test_privilege_reporting():
    assert assert_read_only([{"role": "read", "db": DB}])["write_capable"] is False
    assert assert_read_only([{"role": "readWrite", "db": DB}])["write_capable"] is True
    assert assert_read_only([{"role": "read"}, {"role": "dbOwner"}])["writable_roles"] == ["dbOwner"]


def test_no_write_calls_in_source():
    """The strongest test: grep the application for write operations."""
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    pattern = re.compile(r"\b(insert_one|insert_many|update_one|update_many|"
                         r"delete_one|delete_many|replace_one|bulk_write|"
                         r"find_one_and_\w+|drop|drop_collection|create_index)\s*\(")
    offenders = []
    for f in root.rglob("*.py"):
        if f.name == "demo.py":          # in-memory fixtures only, never a real client
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pattern.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "write operations found:\n" + "\n".join(offenders)
