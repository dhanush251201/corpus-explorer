import React, { useState } from 'react'
import { api } from '../api'
import { Spinner, Err, Empty } from '../components/Bits'
import { buildFilters } from './SearchView'

/**
 * Keyword in context plus collocation - the two staples of corpus linguistics.
 * Left context is rendered right-aligned and RTL-clipped so the keyword column
 * lines up, which is how concordance lines are actually read.
 */
export default function ConcordanceView({ facets, state, setState }) {
  const [term, setTerm] = useState(state.term || '')
  const [kwic, setKwic] = useState(null)
  const [colloc, setColloc] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [sortBy, setSortBy] = useState('none')

  async function run(e) {
    e?.preventDefault()
    if (!term.trim()) return
    setBusy(true); setError(null)
    const body = { term: term.trim(), scope: state.scope, filters: buildFilters(state),
                   window: state.window, limit: 200, sample: 150 }
    try {
      const [k, c] = await Promise.all([api.kwic(body), api.colloc(body)])
      setKwic(k); setColloc(c); setState({ ...state, term: term.trim() })
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const lines = (() => {
    if (!kwic?.lines) return []
    const L = [...kwic.lines]
    if (sortBy === 'left') L.sort((a, b) => rev(a.left).localeCompare(rev(b.left)))
    if (sortBy === 'right') L.sort((a, b) => a.right.localeCompare(b.right))
    if (sortBy === 'source') L.sort((a, b) => a.think_tank.localeCompare(b.think_tank))
    return L
  })()

  return (
    <>
      <aside className="side">
        <div className="sidehead">Scope</div>
        <label className="field">
          <span>Collection</span>
          <select value={state.scope} onChange={(e) => setState({ ...state, scope: e.target.value })}>
            {(facets?.scopes || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Context window (words)</span>
          <input type="number" min="2" max="20" value={state.window}
                 onChange={(e) => setState({ ...state, window: +e.target.value || 8 })} />
        </label>
        <div className="sidehead">Filters</div>
        <label className="field">
          <span>From</span>
          <input type="date" value={state.from}
                 onChange={(e) => setState({ ...state, from: e.target.value })} />
        </label>
        <label className="field">
          <span>To</span>
          <input type="date" value={state.to}
                 onChange={(e) => setState({ ...state, to: e.target.value })} />
        </label>
        <label className="check">
          <input type="checkbox" checked={state.reliableDates}
                 onChange={(e) => setState({ ...state, reliableDates: e.target.checked })} />
          <span>Only trustworthy dates</span>
        </label>

        <div className="sidehead">Sort lines by</div>
        <label className="field">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="none">Order found</option>
            <option value="left">Left context</option>
            <option value="right">Right context</option>
            <option value="source">Institution</option>
          </select>
        </label>
      </aside>

      <main className="content">
        <h2 style={{ fontSize: '1.5rem', marginBottom: 6 }}>Concordance</h2>
        <p className="muted" style={{ fontSize: '.88rem', marginBottom: 16, maxWidth: '62ch' }}>
          Every occurrence of a term with its surrounding words. Sorting by left or right
          context is what surfaces recurring phraseology.
        </p>
        <form className="searchrow" onSubmit={run}>
          <div className="searchbox">
            <input value={term} onChange={(e) => setTerm(e.target.value)}
                   placeholder="a word or phrase"
                   aria-label="Term to concordance" />
          </div>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Analyse'}</button>
        </form>

        <Err error={error} />

        {kwic && (
          <>
            <div className="meta-line">
              <span><b className="tnum">{lines.length}</b> concordance lines</span>
              <span className="muted">from {kwic.documents_scanned} documents sampled</span>
              {kwic.truncated && <span className="muted">· capped</span>}
            </div>
            {lines.length === 0 ? (
              <Empty>No occurrences of “{kwic.term}” in this scope.</Empty>
            ) : (
              <div className="tablewrap">
                <table className="kwic">
                  <tbody>
                    {lines.map((l, i) => (
                      <tr key={i} title={l.title}>
                        <td className="l">{l.left}&nbsp;</td>
                        <td className="m">{l.match}</td>
                        <td className="r">&nbsp;{l.right}</td>
                        <td className="src">{l.think_tank}{l.published_at ? ` · ${l.published_at.slice(0, 7)}` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {colloc?.collocates?.length > 0 && (
          <>
            <h2 style={{ fontSize: '1.25rem', margin: '34px 0 6px' }}>Collocates</h2>
            <p className="muted" style={{ fontSize: '.86rem', marginBottom: 14, maxWidth: '62ch' }}>
              Words appearing within ±{state.window} tokens of the term, ranked by how much
              more often they occur there than in the corpus at large. {colloc.occurrences.toLocaleString()} occurrences.
            </p>
            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr><th>Word</th><th className="num">Near term</th>
                      <th className="num">In corpus</th><th className="num">Ratio</th></tr>
                </thead>
                <tbody>
                  {colloc.collocates.slice(0, 30).map((c) => (
                    <tr key={c.word}>
                      <td><b>{c.word}</b></td>
                      <td className="num tnum">{c.near}</td>
                      <td className="num tnum">{c.corpus.toLocaleString()}</td>
                      <td className="num tnum">{c.score}×</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </>
  )
}

const rev = (s) => s.split('').reverse().join('')
