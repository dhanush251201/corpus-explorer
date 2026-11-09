import React, { useEffect, useState } from 'react'
import { api } from './api'
import { ReadOnlyBadge, KnowledgeWarning, Err } from './components/Bits'
import SearchView from './views/SearchView'
import ConcordanceView from './views/ConcordanceView'
import TrendsView from './views/TrendsView'
import CoverageView from './views/CoverageView'
import SourcesView from './views/SourcesView'
import StatsView from './views/StatsView'

const TABS = [
  ['search', 'Search'],
  ['sources', 'Sources'],
  ['stats', 'Statistics'],
  ['concordance', 'Concordance'],
  ['trends', 'Term frequency'],
  ['coverage', 'Coverage'],
]

const DEFAULTS = {
  tab: 'search', q: '', scope: 'all', sort: 'relevance', page: 0,
  from: '', to: '', genre: '', minWords: '', author: '',
  reliableDates: false, hasPdf: false,
  strip: true, exact: true, useLlm: false, term: '', window: 8,
  terms: [],
  doc: '',            // url of the open document, so it can be linked to
}

/** Search state lives in the URL, so any view is a shareable link. */
function readUrl() {
  const p = new URLSearchParams(location.search)
  const s = { ...DEFAULTS }
  for (const k of Object.keys(DEFAULTS)) {
    if (!p.has(k)) continue
    const v = p.get(k)
    if (typeof DEFAULTS[k] === 'boolean') s[k] = v === '1'
    else if (typeof DEFAULTS[k] === 'number') s[k] = +v || DEFAULTS[k]
    else if (Array.isArray(DEFAULTS[k])) s[k] = v.split('|').filter(Boolean)
    else s[k] = v
  }
  return s
}

function writeUrl(s) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(s)) {
    if (v === DEFAULTS[k] || v === '' || v == null) continue
    if (Array.isArray(v)) { if (v.join('|') !== DEFAULTS[k].join('|')) p.set(k, v.join('|')) }
    else if (typeof v === 'boolean') { if (v) p.set(k, '1') }
    else p.set(k, String(v))
  }
  const qs = p.toString()
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname)
}

export default function App() {
  const [state, setState] = useState(readUrl)
  const [meta, setMeta] = useState(null)
  const [facets, setFacets] = useState(null)
  const [error, setError] = useState(null)
  const [theme, setTheme] = useState(() => localStorage.getItem('ce-theme') || 'system')

  useEffect(() => { writeUrl(state) }, [state])

  useEffect(() => {
    Promise.all([api.meta(), api.facets()])
      .then(([m, f]) => { setMeta(m); setFacets(f) })
      .catch((e) => setError(`Cannot reach the API — ${e.message}`))
  }, [])

  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('ce-theme', theme)
  }, [theme])

  const View = { search: SearchView, sources: SourcesView, stats: StatsView,
                 concordance: ConcordanceView,
                 trends: TrendsView, coverage: CoverageView }[state.tab] || SearchView

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">Corpus Explorer<small>think tank data · 2022–2026</small></div>
        <nav className="tabs" role="tablist">
          {TABS.map(([id, label]) => (
            <button key={id} className="tab" role="tab" aria-selected={state.tab === id}
                    onClick={() => setState({ ...state, tab: id, page: 0 })}>{label}</button>
          ))}
        </nav>
        <span className="spacer" />
        {meta?.demo_mode && <span className="ro-badge warn" title="Serving in-memory fixtures, not the real cluster">demo data</span>}
        <ReadOnlyBadge meta={meta} />
        <button className="iconbtn" title={`Theme: ${theme}`}
                onClick={() => setTheme(theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system')}>
          {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'}
        </button>
      </div>

      {error && <div style={{ padding: '20px 24px' }}><Err error={error} /></div>}
      <KnowledgeWarning meta={meta} />

      {meta && (
        <div className="main">
          <View meta={meta} facets={facets} state={state} setState={setState} />
        </div>
      )}
      {!meta && !error && <div className="empty">connecting…</div>}
    </div>
  )
}
