# Corpus Explorer — backend

The read-only API behind the Corpus Explorer. A FastAPI service that queries the
think tank database (`Top40ThinkTanks`, 19,827 documents, 38 sources, 2022–2026)
and answers JSON under `/api`.

It is a standalone service. It serves no web pages, reads nothing outside this
folder, and is reached by the frontend (`../frontend`) over HTTP from another
origin. Anything that can run Python 3.10+ and reach MongoDB Atlas can host it.

```
backend/
├── app/                 the service (FastAPI)
├── data/
│   ├── corpus_knowledge.json   corpus metadata from the profiling scripts
│   └── stats.json              weekly statistics snapshot (written by the service)
├── fixtures/            demo data for DEMO_MODE and the tests
├── tests/
├── compute_stats.py     recompute the statistics snapshot (for cron)
├── verify_live.py       check the service against the real cluster
├── profile_perf.py      time each stage against the real cluster
├── requirements.txt
└── .env.example         every setting, documented
```

---

## The read-only guarantee

The application cannot write. That is enforced four times over, independently:

**Layer 1 — a MongoDB user that cannot write.** Do this first; it is the only
layer that survives a bug in the other three.

> In Atlas: **Database Access → Add New Database User**. Give it a name like
> `corpus_reader`, and under *Built-in Role* choose **"Only read any database"**.
> Better still, *Custom Role* → `read` on `Top40ThinkTanks` alone. Use that
> user's connection string in `.env`. Do **not** reset the password on an
> existing user — other people's pipelines may depend on it.

**Layer 2 — no write code exists.** `app/db.py` exposes exactly four
operations: `find`, `aggregate`, `count_documents`, `distinct`. Verify it:

```bash
grep -rnE "insert_|update_|delete_|replace_one|bulk_write|drop\(" app/ | grep -v demo.py
```

That returns nothing. (`demo.py` seeds an in-memory mongomock instance for
`DEMO_MODE` and is never given a real connection.) A test fails the build if
anyone adds one: `tests/test_safety.py::test_no_write_calls_in_source`.

**Layer 3 — structural validation.** Every filter and pipeline is walked before
execution and rejected if it contains `$out`, `$merge`, `$function`,
`$accumulator`, `$where`, or a `$lookup`/`$unionWith` reaching another database.
See `app/safety.py`.

**Layer 4 — resource ceilings.** `maxTimeMS` on every query, capped page sizes,
capped skip depth, capped pipeline length and nesting depth.

The service asks the server which roles its connection holds and reports them in
`GET /api/meta`; the frontend shows a red badge when they are write-capable.

---

## Configuration

Settings come from environment variables, or from `backend/.env` (copy
`.env.example`). Real environment variables win over the file, and
`ENV_FILE=/path/to/file` reads a different file. Relative paths resolve from
`backend/`, whatever the working directory.

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI` | — | Connection string. Use the read-only user. |
| `DB_NAME` | `Top40ThinkTanks` | Database. |
| `MASTER_COLLECTION` | `top_40_think_tanks` | The legacy combined collection. |
| `ALLOW_ORIGINS` | `http://localhost:5173,http://localhost:4173` | Comma-separated addresses the frontend is served from (scheme, host, port; no path). Browsers refuse API responses for any other origin. `*` allows all. |
| `KNOWLEDGE_PATH` | `data/corpus_knowledge.json` | Corpus metadata. |
| `STATS_PATH` | `data/stats.json` (`data/stats.demo.json` in demo mode) | Statistics snapshot; must be writable. |
| `STATS_SCHEDULER` | `1` | Recompute the snapshot weekly inside the process. Set `0` with several workers and use cron. |
| `MAX_TIME_MS`, `MAX_PAGE_SIZE`, `MAX_SKIP`, `MAX_EXPORT_ROWS`, `MAX_PIPELINE_STAGES`, `MAX_SCAN_DOCS` | see `app/config.py` | Query ceilings. |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | empty | Optional LLM query parsing. |
| `DEMO_MODE` | `0` | Serve in-memory fixtures instead of the cluster. |

---

## Running locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**With no database at all** — in-memory fixtures that reproduce the real corpus's
quirks:

```bash
DEMO_MODE=1 KNOWLEDGE_PATH=fixtures/knowledge.demo.json uvicorn app.main:app --port 8000
```

Both variables belong to demo mode only; the real-database command sets neither.

**Against the real corpus** — put `MONGO_URI` in `backend/.env`
(`cp .env.example .env`), or point at an existing file such as the RA folder's:

```bash
ENV_FILE=../../.env uvicorn app.main:app --port 8000
```

Then check it against the live cluster before trusting it:

```bash
python3 verify_live.py
```

That checks the connection and its privileges, that the counts match the
profile (16,095 master / 19,827 union), that the text index is present, that
date filters return rows, that search and the analysis paths work, and that two
known corpus bugs still reproduce. It reads only.

`http://localhost:8000/docs` has interactive API documentation. Run the frontend
(`../frontend`, `npm run dev`) to use the explorer itself.

**Tests** (no database needed):

```bash
python3 -m pytest tests/ -q
```

---

## Running on a server

1. **Use the read-only Atlas user** in `MONGO_URI`, and **add the server's IP
   address under Atlas → Network Access**, or every query times out.
2. **Set `ALLOW_ORIGINS`** to the address the frontend is served from, e.g.
   `ALLOW_ORIGINS=https://explorer.example.org`.
3. **Run it behind a reverse proxy with TLS** (nginx, Caddy):

   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
   ```

   With more than one worker, set `STATS_SCHEDULER=0` and schedule the
   statistics job instead (below), or every worker recomputes it separately.
   `GET /api/health` returns 200 when the service can reach the database, for a
   load balancer or uptime check.
4. **`data/` must be writable** by the service user: the statistics snapshot is
   written there.

There is no authentication. If the API is reachable beyond the group, put basic
auth or university SSO in front of it at the proxy — the service assumes everyone
who can reach it may read the corpus.

---

## Statistics snapshot

Corpus-wide figures (total words, longest and shortest articles, the length
distribution, per-source breakdowns) mean scanning every document, which takes
minutes, so they are **computed weekly rather than per request** and cached to
`STATS_PATH`. With `STATS_SCHEDULER=1` a daemon thread checks hourly and
recomputes when the snapshot predates the most recent Sunday 03:00.

> **The snapshot is written to local disk, never to MongoDB.** Nothing about this
> feature changes the read-only guarantee.

Recompute on demand from the frontend (*Statistics → Recompute now*,
`POST /api/stats/refresh`) or from the command line:

```bash
python3 compute_stats.py             # now
python3 compute_stats.py --if-stale  # only if older than the last Sunday
```

To drive the schedule externally:

```
0 3 * * 0  cd /path/to/backend && ./.venv/bin/python compute_stats.py
```

Demo mode keeps its own snapshot (`data/stats.demo.json`), so fixture numbers
never replace the real ones.

---

## What it knows about the corpus

**The list of sources comes from the database, always.** `data/corpus_knowledge.json`
(produced by the profiling scripts; `KNOWLEDGE_PATH` points elsewhere) only
enriches those sources with document counts, coverage dates and boilerplate
patterns. An absent or stale file degrades the detail shown; it can never hide a
source. `GET /api/meta` reports `knowledge_check`, the service logs a warning at
startup when the two disagree, and the frontend shows a banner. After
re-profiling, copy the new file over `data/corpus_knowledge.json`.

Facts baked into the responses:

| Fact | How it surfaces |
|---|---|
| FES (2,968 docs) and PRIO (176) have year-precision dates only | `Date imputed` flag; excluded from trends by default |
| 3,839 documents keep text only in `pdf_text`, 5,390 only in `article_text` | Text is coalesced; word counts report the article; `role` switches between article and full document |
| Six sources are missing from `top_40_think_tanks` | `Outside master collection` flag; the default scope includes them |
| All 614 SWP documents share one title | `Title unreliable` flag |
| Boilerplate reaches 100% of some institutions' documents | Stripped by default (`strip`), count reported per document |

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/` | service description |
| `GET`  | `/api/health` | 200 when the database is reachable |
| `GET`  | `/api/meta` | corpus metadata, limits, read-only status, baked-in caveats |
| `GET`  | `/api/facets` | scopes, institutions, genres, years |
| `POST` | `/api/search` | search; returns hits, flags and the queries issued |
| `GET`  | `/api/sources` | directory of every source with counts and coverage (cached) |
| `GET`  | `/api/stats` | the weekly statistics snapshot |
| `POST` | `/api/stats/refresh` | recompute it now, in the background (writes local disk only) |
| `GET`  | `/api/document?url=&role=` | one document; `role` = auto \| article \| document |
| `GET`  | `/api/document/text?url=` | plain-text download of one document |
| `POST` | `/api/kwic` | concordance lines |
| `POST` | `/api/collocations` | collocates for a term |
| `POST` | `/api/trends` | rate per 1,000 documents per year |
| `GET`  | `/api/coverage` | institution × month grid |
| `POST` | `/api/export?fmt=csv\|json` | export a result set |

Interactive docs at `/docs`. CORS allows `GET` and `POST` only, from
`ALLOW_ORIGINS`.

---

## Optional: LLM query generation

The natural-language parser is deterministic and needs no key. For arbitrary
phrasing, set `ANTHROPIC_API_KEY` and a "Use the model" toggle appears in the
frontend. Generated queries pass through the same layer-3 validator before
executing, and the query inspector always shows what was produced.

---

## Performance notes

Run `python3 profile_perf.py` to see where time goes against the live cluster —
per primitive, per endpoint and per collection. Optimise from that.

- **Search is two-phase.** Phase 1 asks every collection for metadata only — no
  `article_text`, no `pdf_text` — enough to count, rank, merge and page. Phase 2
  fetches only the rows being shown. If you add a field to `LIGHT_FIELDS`, keep
  the text bodies out of it.
- **Phase 2 computes in the database.** `$indexOfCP` locates the search term and
  `$substrCP` returns a window around it, with `$split`/`$size` for an exact word
  count. If the server lacks those operators the code falls back to fetching
  bodies and says so — `GET /api/meta` reports `hydration.mode`.
- **Concordance projects one capped field**, coalesced server-side.
- **Counts are cached per query**, and the fan-out across collections is
  concurrent (`search.parallel`).
- **Static endpoints are cached** in process for 15 minutes — the corpus is a
  frozen snapshot. `db.clear_cache()` drops them.
- Term frequency uses one aggregation per collection per term, grouped by year.

The remaining lever is an index on the cluster — a write, so the professor's
call, not the service's.

## Known limitations

- **Deep paging across multiple collections is capped.** Beyond ~400 rows per
  collection in the all-sources scope, paging is approximate.
- **Concordance and collocation work on a sample** of matching documents (the
  frontend asks for 150; the API allows up to 400).
- **Collocation ranking is a simple ratio**, not log-likelihood or LogDice.
- **Minimum length is approximate** — evaluated on character length at roughly
  six characters per word.
- **Author names are unnormalised.**
- **Search matches surface forms.**
