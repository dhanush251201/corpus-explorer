import React, { useEffect, useState, useCallback } from 'react'
import { api, downloadExport } from '../api'
import { Spinner, Err, Empty, Flags, QueryInspector } from '../components/Bits'

const SORTS = [
  ['relevance', 'Relevance'], ['newest', 'Newest first'], ['oldest', 'Oldest first'],
  ['longest', 'Longest first'], ['institution', 'By source'],
]

/** Mongo-syntax filters. Plain-value filters travel as their own body fields. */
export function buildFilters(s) {
  const f = {}
  if (s.genre) f.publication_group = s.genre
  if (s.reliableDates) f.think_tank = { $nin: ['FES (Friedrich-Ebert-Stiftung)', 'PRIO'] }
  if (s.hasPdf) f.pdf_text = { $nin: ['', null] }
  return f
}

export function searchBody(s, extra = {}) {
  return {
    q: s.q, scope: s.scope, sort: s.sort, page: s.page, size: 25,
    strip_boilerplate: s.strip, natural_language: true, use_llm: s.useLlm,
    exact: s.exact, filters: buildFilters(s),
    min_words: s.minWords ? Number(s.minWords) : null,
    date_from: s.from || null,
    date_to: s.to || null,
    author: s.author || null,
    ...extra,
  }
}

export default function SearchView({ meta, facets, state, setState }) {
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState(state.q || '')

  const run = useCallback(async () => {
    setLoading(true); setError(null)
    try { setRes(await api.search(searchBody(state))) }
    catch (e) { setError(e.message); setRes(null) }
    finally { setLoading(false) }
  }, [state])

  useEffect(() => { run() }, [state.scope, state.sort, state.page, state.strip, state.from,
                              state.to, state.genre, state.reliableDates, state.hasPdf,
                              state.minWords, state.author, state.q, state.exact])

  const submit = (e) => { e?.preventDefault(); setState({ ...state, q: draft, page: 0 }) }
  const scopeLabel = facets?.scopes?.find((s) => s.id === state.scope)?.label || state.scope

  return (
    <>
      <aside className="side">
        <div className="sidehead">Source</div>
        <label className="field">
          <span>Showing</span>
          <select value={state.scope} onChange={(e) => setState({ ...state, scope: e.target.value, page: 0 })}>
            {groupScopes(facets?.scopes).map(([group, items]) =>
              group ? (
                <optgroup key={group} label={group}>
                  {items.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </optgroup>
              ) : items.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)
            )}
          </select>
        </label>
        {state.scope === 'master' && (
          <div className="notice" style={{ fontSize: '.79rem' }}>
            This legacy collection omits six sources and 3,732 documents. Use
            <b> All sources</b> unless you specifically need it.
          </div>
        )}
        {state.scope !== 'all' && state.scope !== 'master' && (
          <button className="btn ghost sm" style={{ marginBottom: 14 }}
                  onClick={() => setState({ ...state, scope: 'all', page: 0 })}>
            ← back to all sources
          </button>
        )}

        <div className="sidehead">Filters</div>
        <label className="field">
          <span>From</span>
          <input type="date" value={state.from}
                 onChange={(e) => setState({ ...state, from: e.target.value, page: 0 })} />
        </label>
        <label className="field">
          <span>To</span>
          <input type="date" value={state.to}
                 onChange={(e) => setState({ ...state, to: e.target.value, page: 0 })} />
        </label>
        <label className="field">
          <span>Document type</span>
          <select value={state.genre} onChange={(e) => setState({ ...state, genre: e.target.value, page: 0 })}>
            <option value="">Any type</option>
            {(facets?.genres || []).map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Author contains</span>
          <input type="text" value={state.author} placeholder="surname"
                 onChange={(e) => setState({ ...state, author: e.target.value, page: 0 })} />
        </label>
        <label className="field">
          <span>Minimum length (words, approx.)</span>
          <input type="number" min="0" step="50" value={state.minWords}
                 onChange={(e) => setState({ ...state, minWords: e.target.value, page: 0 })} />
        </label>

        <div className="sidehead">Data quality</div>
        <label className="check" title="Excludes FES and PRIO, whose dates carry year precision only.">
          <input type="checkbox" checked={state.reliableDates}
                 onChange={(e) => setState({ ...state, reliableDates: e.target.checked, page: 0 })} />
          <span>Only trustworthy dates<br /><span className="muted">excludes FES and PRIO</span></span>
        </label>
        <label className="check" title="Only documents that have extracted PDF text.">
          <input type="checkbox" checked={state.hasPdf}
                 onChange={(e) => setState({ ...state, hasPdf: e.target.checked, page: 0 })} />
          <span>Has PDF text</span>
        </label>
        <label className="check" title="Removes the repeated opening phrases each scraper leaked.">
          <input type="checkbox" checked={state.strip}
                 onChange={(e) => setState({ ...state, strip: e.target.checked })} />
          <span>Strip boilerplate</span>
        </label>
        <label className="check" title="On: a multi-word query matches only that exact phrase. Off: broader index-only matching.">
          <input type="checkbox" checked={state.exact}
                 onChange={(e) => setState({ ...state, exact: e.target.checked, page: 0 })} />
          <span>Exact phrase<br /><span className="muted">off = any of the words</span></span>
        </label>

        <div className="sidehead">Sort</div>
        <label className="field">
          <select value={state.sort} onChange={(e) => setState({ ...state, sort: e.target.value, page: 0 })}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>

        {meta?.llm_available && (
          <>
            <div className="sidehead">Query understanding</div>
            <label className="check">
              <input type="checkbox" checked={state.useLlm}
                     onChange={(e) => setState({ ...state, useLlm: e.target.checked, page: 0 })} />
              <span>Use the model<br /><span className="muted">falls back to pattern matching</span></span>
            </label>
          </>
        )}
      </aside>

      <main className="content">
        <form className="searchrow" onSubmit={submit}>
          <div className="searchbox">
            <span className="muted" aria-hidden>⌕</span>
            <input value={draft} onChange={(e) => setDraft(e.target.value)}
                   placeholder={`Search ${scopeLabel} — or leave empty to browse`}
                   aria-label="Search the database" />
            {draft && <button type="button" className="btn ghost sm"
                              onClick={() => { setDraft(''); setState({ ...state, q: '', page: 0 }) }}>clear</button>}
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {loading ? <Spinner /> : 'Search'}
          </button>
        </form>

        <Err error={error} onRetry={run} />
        <QueryInspector result={res} />

        {res && (
          <div className="meta-line">
            <span><b className="tnum">{res.total.toLocaleString()}</b> documents
              {res.counts_approximate && <span className="muted" title="Length filtering happened after fetching, so this is a floor rather than an exact total."> (at least)</span>}
            </span>
            <span className="muted">showing {res.returned} · page {res.page + 1}</span>
            <span style={{ flex: 1 }} />
            <button className="btn ghost sm" onClick={() => downloadExport(searchBody(state), 'csv')}>Export CSV</button>
            <button className="btn ghost sm" onClick={() => downloadExport(searchBody(state), 'json')}>JSON</button>
          </div>
        )}

        {res?.by_source?.length > 1 && (
          <div className="chips" aria-label="Results by source">
            {res.by_source.slice(0, 14).map((b) => (
              <button key={b.collection} className="chip"
                      title={`Show only ${b.institution}`}
                      onClick={() => setState({ ...state, scope: b.institution, page: 0 })}>
                {b.institution}<b className="tnum">{b.count.toLocaleString()}</b>
              </button>
            ))}
            {res.by_source.length > 14 &&
              <span className="muted" style={{ fontSize: '.79rem', alignSelf: 'center' }}>
                +{res.by_source.length - 14} more
              </span>}
          </div>
        )}

        {loading && !res && <Empty><Spinner /> searching…</Empty>}
        {res && res.hits.length === 0 && (
          <Empty>Nothing matched. Try widening the source, or clearing a filter.</Empty>
        )}

        {res?.hits.map((h) => (
          <article key={h.id + h.url} className="card hit" onClick={() => setState({ ...state, doc: h.url })}
                   tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setState({ ...state, doc: h.url })}>
            <div className="hit-title">{h.title}</div>
            <div className="hit-meta">
              <b>{h.think_tank}</b>
              {h.publication_group && <span>{h.publication_group}</span>}
              {h.published_at && <span className="tnum">{h.published_at.slice(0, 10)}</span>}
              <span className="tnum" title={wordTitle(h)}>{h.word_count.toLocaleString()} words</span>
              {h.authors?.length > 0 && <span>{h.authors.slice(0, 3).join(', ')}</span>}
            </div>
            {h.snippet && <div className="hit-snip" dangerouslySetInnerHTML={{ __html: h.snippet }} />}
            <Flags flags={h.flags} />
          </article>
        ))}

        {res && res.total > 25 && (
          <div className="pager">
            <button className="btn ghost sm" disabled={state.page === 0}
                    onClick={() => setState({ ...state, page: state.page - 1 })}>← previous</button>
            <span className="muted tnum">page {state.page + 1}</span>
            <button className="btn ghost sm" disabled={res.returned < 25}
                    onClick={() => setState({ ...state, page: state.page + 1 })}>next →</button>
          </div>
        )}
      </main>

      {state.doc && <DocDrawer url={state.doc} scope={state.scope} strip={state.strip}
                               onClose={() => setState({ ...state, doc: '' })} />}
    </>
  )
}

function wordTitle(h) {
  const v = h.variants || {}
  const bits = []
  if (v.article) bits.push(`article: ${v.article.words.toLocaleString()} words`)
  if (v.document) bits.push(`full PDF: ${v.document.words.toLocaleString()} words`)
  return bits.join(' · ') || ''
}

function groupScopes(scopes) {
  if (!scopes) return []
  const out = new Map()
  for (const s of scopes) {
    const g = s.group || ''
    if (!out.has(g)) out.set(g, [])
    out.get(g).push(s)
  }
  return [...out.entries()]
}

function DocDrawer({ url, scope, strip, onClose }) {
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)
  const [role, setRole] = useState('auto')
  const [showRaw, setShowRaw] = useState(false)

  useEffect(() => {
    let alive = true
    setDoc(null)
    api.document(url, scope, role)
      .then((d) => alive && setDoc(d))
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [url, scope, role])

  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const v = doc?.variants || {}
  const both = v.article && v.document

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Document">
        <header>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: '1.22rem', lineHeight: 1.25 }}>{doc?.title || 'Loading…'}</h2>
            {doc && (
              <div className="hit-meta" style={{ marginTop: 6, marginBottom: 0 }}>
                <b>{doc.think_tank}</b>
                {doc.published_at && <span className="tnum">{doc.published_at.slice(0, 10)}</span>}
              </div>
            )}
          </div>
          <button className="iconbtn" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="scroll">
          <Err error={error} />
          {!doc && !error && <Empty><Spinner /> loading…</Empty>}
          {doc && (
            <>
              <Flags flags={doc.flags} />

              {both && (
                <div className="segmented" role="group" aria-label="Which text to show">
                  <button className={doc.text_role === 'article' ? 'on' : ''}
                          onClick={() => setRole('article')}>
                    Article <span className="tnum">{v.article.words.toLocaleString()}w</span>
                  </button>
                  <button className={doc.text_role === 'document' ? 'on' : ''}
                          onClick={() => setRole('document')}>
                    Full document <span className="tnum">{v.document.words.toLocaleString()}w</span>
                  </button>
                </div>
              )}
              {both && (
                <p className="muted" style={{ fontSize: '.8rem', margin: '2px 0 12px' }}>
                  The full document is the PDF rendering — it includes running headers, page
                  numbers and cover material, which is why it is longer.
                </p>
              )}

              <dl className="kv">
                <dt>Source</dt>
                <dd>
                  <a href={doc.url} target="_blank" rel="noreferrer">{doc.url}</a>
                  {doc.pdf_url && <> · <a href={doc.pdf_url} target="_blank" rel="noreferrer">PDF</a></>}
                </dd>
                <dt>Authors</dt><dd>{doc.authors?.join(', ') || '—'}</dd>
                <dt>Type</dt><dd>{doc.publication_group || '—'}</dd>
                <dt>Collection</dt><dd className="mono">{doc.collection}</dd>
                <dt>Showing</dt>
                <dd>
                  {doc.text_role === 'article' ? 'the web article' : 'the full PDF text'}
                  {' '}(<code>{doc.text_source}</code>) — {doc.word_count.toLocaleString()} words
                  {doc.boilerplate_removed > 0 &&
                    <span className="muted"> · {doc.boilerplate_removed} boilerplate pattern(s) removed</span>}
                </dd>
              </dl>

              <div style={{ display: 'flex', gap: 8, margin: '6px 0 16px', flexWrap: 'wrap' }}>
                <button className="btn ghost sm" onClick={() => setShowRaw(!showRaw)}>
                  {showRaw ? 'Show cleaned text' : 'Show raw text'}
                </button>
                <a className="btn ghost sm" style={{ textDecoration: 'none', lineHeight: '26px' }}
                   href={api.textUrl(doc.url, scope, doc.text_role)}>Download text</a>
                <button className="btn ghost sm" onClick={() => {
                  navigator.clipboard?.writeText(window.location.href)
                }} title="Copy a link to this document">Copy link</button>
              </div>

              <div className="doctext">{showRaw ? doc.raw_text : doc.text}</div>
            </>
          )}
        </div>
      </aside>
    </>
  )
}
