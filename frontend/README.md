# Corpus Explorer — frontend

The browser interface to the think tank corpus. A React single-page app, built
with Vite into plain static files (`dist/`) that any web server can host. It talks
to the backend API (`../backend`) over HTTP; the two are deployed independently.

---

## What it does

**Search** — full-text search across the database. Type naturally:
`ECFR policy briefs since 2024 mentioning "de-risking"` is parsed into a real
query, and the **query inspector** shows what was built and why. Filters for date
range, document type, author, minimum length, trustworthy dates only, has PDF
text, and strip boilerplate. Results carry a per-source breakdown you can click
to narrow. Export any result set to CSV or JSON.

**Reader** — opens a document beside the results. Where a document has both a web
article and a PDF, it switches between **Article** and **Full document**. Show the
raw or cleaned text, download it as plain text, or copy a link to it.

**Sources** — every source with its document count, date coverage and which text
fields it carries.

**Statistics** — corpus-wide figures: documents, words, authors, the longest and
shortest documents, the length distribution, documents per year, a data-quality
tally and per-source breakdowns. These come from the backend's weekly snapshot;
*Recompute now* refreshes it.

**Concordance** — every occurrence of a term in context, sortable by left
context, right context or institution, with collocates ranked below.

**Term frequency** — up to four terms charted as a rate per 1,000 documents per
year. Institutions with imputed dates are excluded by default.

**Coverage** — institution × month heat map, the view that makes scraper gaps
visible.

Every view's state lives in the URL query string, including which document is
open, so any screen is a shareable link. Light, dark and system themes.

---

## Pointing it at the backend

The backend's address is read at runtime from **`config.js`** (`public/config.js`
in the source, `dist/config.js` after a build):

```js
window.CORPUS_EXPLORER_CONFIG = {
  apiBase: "https://api.explorer.example.org",
};
```

`apiBase` is the scheme, host and port the backend answers on — no trailing
slash, no `/api`. Edit `dist/config.js` on the server to change it; no rebuild is
needed, so one build can be deployed anywhere.

Leave `apiBase` empty to call the page's own origin. That is what the dev and
preview servers do (they forward `/api` to the backend), and it works in
production when the web server proxies `/api` to the backend (see below).

`VITE_API_BASE` at build time sets a fallback used only when `config.js` leaves
`apiBase` empty (see `.env.example`).

Whatever the setup, **the backend's `ALLOW_ORIGINS` must include the address this
frontend is served from**, unless `/api` is proxied through the same origin.

---

## Developing

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, forwards /api to http://localhost:8000
```

Start the backend on port 8000 first (see `../backend/README.md`; demo mode needs
no database). `DEV_API_TARGET=http://host:port` forwards elsewhere.

```bash
npm run build      # writes dist/
npm run preview    # serves dist/ on http://localhost:4173, forwarding /api the same way
```

---

## Deploying

`npm run build` produces `dist/`: `index.html`, `config.js` and `assets/`. Upload
that folder to any static host: nginx, Apache, a university web space, GitHub
Pages, Netlify, S3. Asset paths are relative, so it works at the site root or in
a sub-directory (`https://server/explorer/`). No server-side routing is needed,
because the app keeps its state in the query string.

**Separate origins** (frontend and API on different hosts or ports): set
`apiBase` in `dist/config.js` to the API's address, and add the frontend's
address to the backend's `ALLOW_ORIGINS`.

**Same origin** (one web server in front of both): leave `apiBase` empty and
proxy `/api` to the backend. With nginx:

```nginx
server {
    listen 443 ssl;
    server_name explorer.example.org;

    root /var/www/corpus-explorer/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_read_timeout 300s;        # exports and first searches can be slow
    }
}
```

`config.js` should not be cached for long, so a changed API address takes effect;
the files under `assets/` have content hashes in their names and can be cached
indefinitely.

---

## When it cannot reach the API

The error banner names the address it tried:

- **"no response from …"** — the backend is down, `apiBase` is wrong, or the
  backend's `ALLOW_ORIGINS` does not include this page's origin (a refused CORS
  request looks the same as a network failure to the page).
- **"… answered … with a web page, not the API"** — the request reached
  something other than the backend, usually a static host because `apiBase` is
  empty or wrong.

The page also needs `fonts.googleapis.com` for its typefaces; without it the
browser falls back to system fonts.
