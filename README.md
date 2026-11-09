# Corpus Explorer

A read-only web interface to the think tank database (`Top40ThinkTanks`,
19,827 documents, 38 sources, 2022–2026). It is a way into the whole database:
search, read, export, concordance, term frequency, coverage and corpus
statistics, with what the profiling work found about the data (imputed dates,
text split across two fields, boilerplate, the sources missing from the old
master collection) surfaced on every result.

It is two independent applications:

| | What it is | Runs on | Details |
|---|---|---|---|
| [`backend/`](backend/) | FastAPI service, JSON under `/api`, read-only against MongoDB | any host with Python 3.10+ that can reach Atlas | [backend/README.md](backend/README.md) |
| [`frontend/`](frontend/) | React single-page app, built to static files | any static web host | [frontend/README.md](frontend/README.md) |

```
  browser ──── static files ────▶  frontend host   (index.html, config.js, assets/)
     │
     └──── fetch /api/* ─────────▶  backend host   ───▶  MongoDB Atlas (read only)
           (apiBase in config.js;   (ALLOW_ORIGINS
            CORS)                    names the frontend)
```

Neither imports, builds or serves the other. They meet at two settings:
**`apiBase`** in the frontend's `config.js` says where the API is, and
**`ALLOW_ORIGINS`** in the backend's environment says which frontend addresses
may call it. Each folder can be copied to its own server or repository.

---

## Running both locally

```bash
# terminal 1 - the API on :8000 (demo data, no database needed)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEMO_MODE=1 KNOWLEDGE_PATH=fixtures/knowledge.demo.json uvicorn app.main:app --port 8000

# terminal 2 - the interface on :5173, forwarding /api to :8000
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. For the real corpus, start the backend with
`ENV_FILE=../../.env` (the RA folder's credentials) or a `backend/.env` instead of
the two demo variables.

## Deploying to a server

1. **Backend** — on the API host: create a read-only Atlas user, put its
   `MONGO_URI` and the frontend's address (`ALLOW_ORIGINS`) in the environment,
   allow the host under Atlas Network Access, run uvicorn behind a TLS proxy.
   [Steps](backend/README.md#running-on-a-server).
2. **Frontend** — `npm run build`, set `apiBase` in `dist/config.js` to the
   backend's address, upload `dist/` to any static host.
   [Steps](frontend/README.md#deploying).

Or put one web server in front of both: serve `dist/` and proxy `/api` to the
backend, and leave `apiBase` empty.

There is no authentication. If either part is reachable beyond the group, put
basic auth or university SSO in front of it.
