// Where the backend lives. config.js (loaded before the app, editable on the
// server) wins over the build-time VITE_API_BASE; empty means this page's own
// origin, which the Vite dev and preview servers proxy to the backend.
const runtime = window.CORPUS_EXPLORER_CONFIG || {}
export const API_BASE = String(runtime.apiBase || import.meta.env.VITE_API_BASE || '')
  .trim().replace(/\/+$/, '')
const BASE = API_BASE
const WHERE = API_BASE || `${location.origin} (same origin)`

async function send(path, opts) {
  try {
    return await fetch(BASE + path, opts)
  } catch {
    // A network failure and a CORS refusal look identical from here.
    throw new Error(`no response from ${WHERE}. Check that the backend is running, that ` +
      `apiBase in config.js points at it, and that its ALLOW_ORIGINS includes ${location.origin}.`)
  }
}

async function call(path, opts = {}) {
  const r = await send(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const body = await r.text()
  let data = null
  try { data = JSON.parse(body) } catch { /* not JSON - handled below */ }

  if (data === null) {
    // A web page instead of JSON: the request reached something other than the
    // API - usually a static host because apiBase is wrong, or an old backend.
    const looksLikeHtml = body.trimStart().startsWith('<')
    throw new Error(looksLikeHtml
      ? `${WHERE} answered ${path} with a web page, not the API. Check apiBase in config.js ` +
        `(or that the backend is not older than this frontend).`
      : `${r.status} ${r.statusText}: unexpected response from ${path}`)
  }
  if (!r.ok) throw new Error(data.detail || `${r.status} ${r.statusText}`)
  return data
}

export const api = {
  meta:     ()      => call('/api/meta'),
  facets:   ()      => call('/api/facets'),
  search:   (body)  => call('/api/search',       { method: 'POST', body: JSON.stringify(body) }),
  document: (url, scope, role = 'auto') =>
    call(`/api/document?url=${encodeURIComponent(url)}&scope=${encodeURIComponent(scope)}&role=${role}`),
  sources:  ()      => call('/api/sources'),
  stats:    ()      => call('/api/stats'),
  refreshStats: ()  => call('/api/stats/refresh', { method: 'POST', body: '{}' }),
  textUrl:  (url, scope, role = 'auto') =>
    `${BASE}/api/document/text?url=${encodeURIComponent(url)}&scope=${encodeURIComponent(scope)}&role=${role}`,
  kwic:     (body)  => call('/api/kwic',         { method: 'POST', body: JSON.stringify(body) }),
  colloc:   (body)  => call('/api/collocations', { method: 'POST', body: JSON.stringify(body) }),
  trends:   (body)  => call('/api/trends',       { method: 'POST', body: JSON.stringify(body) }),
  coverage: (scope) => call(`/api/coverage?scope=${encodeURIComponent(scope)}`),
}

export function downloadExport(body, fmt) {
  return send(`/api/export?fmt=${fmt}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then((r) => { if (!r.ok) throw new Error(`Export failed (${r.status})`); return r.blob() })
    .then((blob) => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `corpus_export.${fmt}`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 2000)
    })
}
