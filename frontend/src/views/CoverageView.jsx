import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, Err, Empty } from '../components/Bits'

/**
 * Institution x month document counts. Sequential single hue - this encodes
 * magnitude, not identity - with zero rendered as an empty cell so gaps read
 * as gaps rather than as low values.
 */
export default function CoverageView({ state, setState, facets }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setBusy(true); setError(null)
    api.coverage(state.scope === 'master' ? 'master' : 'union')
      .then(setData).catch((e) => setError(e.message)).finally(() => setBusy(false))
  }, [state.scope])

  const max = data ? Math.max(1, ...data.rows.flatMap((r) => r.counts)) : 1
  const shade = (n) => {
    if (!n) return 'var(--surface-2)'
    const t = Math.min(1, Math.sqrt(n / max))
    return `color-mix(in oklab, var(--accent) ${Math.round(18 + t * 82)}%, var(--surface))`
  }

  return (
    <>
      <aside className="side">
        <div className="sidehead">Scope</div>
        <label className="field">
          <span>Collection</span>
          <select value={state.scope} onChange={(e) => setState({ ...state, scope: e.target.value })}>
            <option value="master">Master collection</option>
            <option value="union">All institutions</option>
          </select>
        </label>
        <div className="notice" style={{ fontSize: '.79rem' }}>
          Empty cells are months with no documents. A long empty band inside an
          institution's active span usually means the scraper stopped, not that the
          institution stopped publishing.
        </div>
      </aside>

      <main className="content">
        <h2 style={{ fontSize: '1.5rem', marginBottom: 6 }}>Coverage</h2>
        <p className="muted" style={{ fontSize: '.88rem', marginBottom: 18, maxWidth: '64ch' }}>
          Documents per institution per month. Institutions marked <b>imputed</b> have
          year-precision dates only — their output is stacked into January and the row
          says nothing about real publishing rhythm.
        </p>

        <Err error={error} />
        {busy && <Empty><Spinner /> loading…</Empty>}

        {data && (
          <>
            <div className="legend">
              <span className="key"><span className="sw" style={{ background: 'var(--surface-2)' }} />no documents</span>
              <span className="key"><span className="sw" style={{ background: shade(max * 0.15) }} />few</span>
              <span className="key"><span className="sw" style={{ background: shade(max) }} />many</span>
              <span className="muted">{data.months.length} months · {data.rows.length} institutions</span>
            </div>

            <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
              <div style={{ minWidth: Math.max(560, data.months.length * 11 + 210) }}>
                {data.rows.map((r) => (
                  <div key={r.institution} className="heatrow"
                       style={{ gridTemplateColumns: `200px repeat(${data.months.length}, 1fr)`, marginBottom: 2 }}>
                    <div className="heatname" title={`${r.institution} — ${r.total} documents`}>
                      {r.imputed_dates && <span className="flag critical" style={{ marginRight: 5 }}>imputed</span>}
                      {r.institution}
                    </div>
                    {r.counts.map((n, i) => (
                      <div key={i} className="heatcell" style={{ background: shade(n) }}
                           title={`${r.institution} · ${data.months[i]}: ${n} document${n === 1 ? '' : 's'}`} />
                    ))}
                  </div>
                ))}
                <div className="heatrow" style={{ gridTemplateColumns: `200px repeat(${data.months.length}, 1fr)`, marginTop: 6 }}>
                  <div />
                  {data.months.map((m, i) => (
                    <div key={m} style={{ fontSize: '.58rem', color: 'var(--ink-3)', textAlign: 'center',
                                          fontFamily: 'IBM Plex Mono, monospace' }}>
                      {m.endsWith('-01') ? m.slice(2, 4) : ''}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="tablewrap" style={{ marginTop: 26 }}>
              <table className="data">
                <thead>
                  <tr><th>Institution</th><th className="num">Documents</th>
                      <th className="num">Months with output</th><th>First</th><th>Last</th></tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => {
                    const nz = r.counts.map((n, i) => (n ? i : -1)).filter((i) => i >= 0)
                    const behind = nz.length ? data.months.length - 1 - nz[nz.length - 1] : 0
                    return (
                      <tr key={r.institution}>
                        <td>{r.institution}{r.imputed_dates &&
                          <span className="flag critical" style={{ marginLeft: 7 }}>imputed dates</span>}</td>
                        <td className="num tnum">{r.total.toLocaleString()}</td>
                        <td className="num tnum">{nz.length} / {data.months.length}</td>
                        <td className="tnum">{nz.length ? data.months[nz[0]] : '—'}</td>
                        <td className="tnum">
                          {nz.length ? data.months[nz[nz.length - 1]] : '—'}
                          {behind >= 3 && <span className="flag warning" style={{ marginLeft: 7 }}>{behind} mo behind</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </>
  )
}
