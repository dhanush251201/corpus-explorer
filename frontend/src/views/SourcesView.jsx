import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, Err, Empty } from '../components/Bits'

/**
 * The directory. "What is actually in here" is the first question anyone opens
 * a database tool with, and until now the app had no answer to it.
 */
export default function SourcesView({ state, setState }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [sort, setSort] = useState('documents')
  const [q, setQ] = useState('')

  useEffect(() => {
    api.sources().then(setData).catch((e) => setError(e.message))
  }, [])

  const rows = (() => {
    if (!data) return []
    let r = data.sources.filter((s) => s.name.toLowerCase().includes(q.toLowerCase()))
    if (sort === 'documents') r = [...r].sort((a, b) => b.documents - a.documents)
    if (sort === 'name') r = [...r].sort((a, b) => a.name.localeCompare(b.name))
    if (sort === 'last') r = [...r].sort((a, b) => (b.last || '').localeCompare(a.last || ''))
    return r
  })()

  const open = (name) => setState({ ...state, tab: 'search', scope: name, page: 0, q: '' })

  return (
    <>
      <aside className="side">
        <div className="sidehead">Find a source</div>
        <label className="field">
          <span>Filter by name</span>
          <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. ECFR" />
        </label>
        <div className="sidehead">Sort</div>
        <label className="field">
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="documents">Most documents</option>
            <option value="name">Name</option>
            <option value="last">Most recent</option>
          </select>
        </label>
        {data && (
          <div className="notice" style={{ fontSize: '.79rem' }}>
            {data.total.toLocaleString()} documents across {data.sources.length} sources,
            {' '}{data.coverage_months?.first} to {data.coverage_months?.last}.
          </div>
        )}
      </aside>

      <main className="content">
        <h2 style={{ fontSize: '1.5rem', marginBottom: 6 }}>Sources</h2>
        <p className="muted" style={{ fontSize: '.88rem', marginBottom: 18, maxWidth: '66ch' }}>
          Every source in the database. <b>Article</b> and <b>PDF</b> show what share of each
          source's documents carry text in that field — they differ a lot, and which one is
          populated decides what you can read. Click a row to browse it.
        </p>

        <Err error={error} />
        {!data && !error && <Empty><Spinner /> loading…</Empty>}

        {data && (
          <div className="tablewrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Source</th>
                  <th className="num">Documents</th>
                  <th className="num">Article</th>
                  <th className="num">PDF</th>
                  <th>Coverage</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.collection} style={{ cursor: 'pointer' }} onClick={() => open(s.name)}
                      tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && open(s.name)}>
                    <td><b style={{ color: 'var(--ink)' }}>{s.name}</b></td>
                    <td className="num tnum">{s.documents.toLocaleString()}</td>
                    <td className="num tnum">{s.article_pct != null ? `${s.article_pct}%` : '—'}</td>
                    <td className="num tnum">{s.pdf_pct != null ? `${s.pdf_pct}%` : '—'}</td>
                    <td className="tnum" style={{ whiteSpace: 'nowrap' }}>
                      {s.first || '—'} → {s.last || '—'}
                    </td>
                    <td>
                      <div className="flags" style={{ marginTop: 0 }}>
                        {s.imputed_dates &&
                          <span className="flag critical" title="Year-precision dates only; month and day were fabricated at ingest.">▲ dates imputed</span>}
                        {s.broken_titles &&
                          <span className="flag critical" title="All documents share one title taken from the site logo.">▲ titles broken</span>}
                        {s.outside_master &&
                          <span className="flag info" title="Absent from top_40_think_tanks because its collection name lacks the `tanks.` prefix.">· outside master</span>}
                        {s.stopped_early &&
                          <span className="flag warning" title={`Last document ${s.stopped_early.last_month}`}>● {s.stopped_early.months_behind} mo behind</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  )
}
