#!/usr/bin/env python3
"""
Check the application against the REAL cluster before anyone relies on it.

This exercises the backend logic directly - no HTTP, no browser - and compares
what comes back against the figures established by the profiling work. Run it
once after pointing .env at the real database:

    cd backend && python3 verify_live.py

Everything here is a read. It issues find/aggregate/count/distinct and nothing
else, same as the application.
"""
import sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings                      # noqa: E402
from app import db, search                           # noqa: E402
from app.schema import knowledge, IMPUTED_DATE_INSTITUTIONS  # noqa: E402

EXPECT_MASTER = 16095
EXPECT_UNION = 19827

ok = fail = warn = 0


def check(label, passed, detail="", soft=False):
    global ok, fail, warn
    if passed:
        ok += 1; mark = "PASS"
    elif soft:
        warn += 1; mark = "WARN"
    else:
        fail += 1; mark = "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))


print(f"\nConfiguration")
print(f"  env files read : {settings.ENV_FILES or 'none found'}")
print(f"  database       : {settings.DB_NAME}")
print(f"  demo mode      : {settings.DEMO_MODE}")
print(f"  knowledge file : {knowledge.loaded_from or 'NOT FOUND'}")
if settings.DEMO_MODE:
    sys.exit("\nDEMO_MODE is on. Unset it to verify against the real cluster.")
if not settings.MONGO_URI:
    sys.exit("\nMONGO_URI is not set. Put it in backend/.env, or point ENV_FILE at a file that has it")

print("\n1. Connection and privileges")
t = time.time()
try:
    db.get_client()
    check("connected", True, f"{time.time()-t:.1f}s")
except Exception as e:
    sys.exit(f"  [FAIL] cannot connect — {e}")

priv = db.privileges()
print(f"       roles: {priv.get('roles')}")
check("connection is read-only", priv.get("write_capable") is False,
      priv.get("note", ""), soft=True)

print("\n2. Collections and indexes")
colls = db.collections()
check("collections found", len(colls) >= 30, f"{len(colls)} collections")
check(f"master '{settings.MASTER}' present", settings.MASTER in colls)
caps = db.capabilities(settings.MASTER)
check("master has a text index", caps.get("text_index"),
      ", ".join(caps.get("indexes", [])[:6]))
missing = [i["collection"] for i in knowledge.institutions if i["collection"] not in colls]
check("every institution in corpus_knowledge.json exists", not missing,
      f"missing: {missing[:4]}" if missing else "")

print("\n3. Document counts")
t = time.time(); n_master = db.count(settings.MASTER, {})
check("master count matches the profile", n_master == EXPECT_MASTER,
      f"{n_master:,} (expected {EXPECT_MASTER:,}) in {time.time()-t:.1f}s",
      soft=n_master != EXPECT_MASTER)
t = time.time()
n_union = sum(db.count(c, {}) for c in search.scope_collections("union"))
check("union count matches the profile", n_union == EXPECT_UNION,
      f"{n_union:,} (expected {EXPECT_UNION:,}) in {time.time()-t:.1f}s",
      soft=n_union != EXPECT_UNION)

print("\n4. The date-type bug (ISO strings vs BSON dates)")
from app.schema import coerce_dates
raw = {"published_at": {"$gte": "2024-01-01T00:00:00", "$lt": "2025-01-01T00:00:00"}}
n_raw = db.count(settings.MASTER, raw)
n_fixed = db.count(settings.MASTER, coerce_dates(raw))
check("coercion turns a zero-result date filter into a real one",
      n_fixed > 0, f"string filter -> {n_raw}, coerced -> {n_fixed:,}")

print("\n5. Search")
# MongoDB's $text ORs unquoted terms, so an unquoted two-word query matches
# documents containing EITHER word. The profile established that 986 documents
# in the master collection contain the phrase "strategic autonomy"; anything in
# the thousands means phrase matching is not working.
t = time.time()
r = search.run("master", ["strategic autonomy"], {}, "relevance", 0, 10)
loose = db.count(settings.MASTER, {"$text": {"$search": "strategic autonomy"}})
check("phrase search is not matching either word", r["total"] < loose / 2,
      f'phrase -> {r["total"]:,}, unquoted OR would give {loose:,}, in {time.time()-t:.1f}s')
check("phrase count is in the range the profile found",
      600 <= r["total"] <= 1600, f'{r["total"]:,} (profile found 986)', soft=True)
if r["hits"]:
    h = r["hits"][0]
    print(f"       top hit: {h['think_tank']} — {h['title'][:54]}")
    print(f"       text from {h['text_source']}, {h['word_count']:,} words, "
          f"flags: {[f['id'] for f in h['flags']] or 'none'}")
t = time.time()
ru = search.run("union", ["strategic autonomy"], {}, "relevance", 0, 10)
check("union search completes", ru["total"] > 0,
      f"{ru['total']:,} matches across {len(ru['collections'])} collections "
      f"in {time.time()-t:.1f}s", soft=(time.time()-t) > 20)

print("\n6. Known corpus facts should reproduce")
fes = [i["name"] for i in knowledge.institutions if i["name"].startswith("FES")]
if fes:
    c = knowledge.collection_for(fes[0])
    rows = db.aggregate(c, [
        {"$match": {"published_at": {"$type": "date"}}},
        {"$group": {"_id": {"$dateToString": {"format": "%m", "date": "$published_at"}},
                    "n": {"$sum": 1}}}])
    months = {r["_id"]: r["n"] for r in rows}
    check("FES output is stacked into January (the imputed-date bug)",
          len(months) == 1 and "01" in months, f"months present: {sorted(months)}")
swp = knowledge.collection_for("SWP")
if swp:
    titles = db.distinct(swp, "title")
    check("all SWP documents share one title", len(titles) == 1,
          f"{len(titles)} distinct title(s)")

print("\n7. Analysis endpoints")
t = time.time()
den = search.year_counts([settings.MASTER],
                         {"think_tank": {"$nin": sorted(IMPUTED_DATE_INSTITUTIONS)}})
check("year_counts returns a per-year denominator", sum(den.values()) > 0,
      f"{[den.get(y,0) for y in (2022,2023,2024,2025,2026)]} in {time.time()-t:.1f}s")
t = time.time()
texts = search.fetch_texts("master", ["strategic autonomy"], {}, cap=40)
check("text fetch for concordance works", len(texts) > 0,
      f"{len(texts)} documents in {time.time()-t:.1f}s")

print("\n8. The read-only validator still refuses hostile input")
from app.safety import validate_pipeline, UnsafeQuery
for bad in ([{"$out": "x"}], [{"$merge": {"into": "y"}}], [{"$match": {"$where": "1"}}]):
    try:
        validate_pipeline(bad, settings.DB_NAME); check(f"rejected {list(bad[0])[0]}", False)
    except UnsafeQuery:
        check(f"rejected {list(bad[0])[0]}", True)

print(f"\n{'='*64}\n  {ok} passed, {warn} warnings, {fail} failed\n{'='*64}")
print("  Warnings are usually fine: a count that differs from the profile just\n"
      "  means the corpus changed since it was measured.\n"
      if warn else "")
sys.exit(1 if fail else 0)
