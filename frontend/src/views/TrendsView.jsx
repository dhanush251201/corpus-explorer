import React, { useState, useEffect } from 'react'
import { api } from '../api'
import { Spinner, Err, Empty } from '../components/Bits'

// Validated categorical palette (CVD-separated, contrast-checked in both themes).
const COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)']

export default function TrendsView({ facets, state, setState }) {
  const [input, setInput] = useState(state.terms?.join(', ') || '')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(e) {
    e?.preventDefault()
    const terms = input.split(',').map((t) => t.trim()).filter(Boolean).slice(0, 4)
    if (!terms.length) return
    setBusy(true); setError(null)
    try {
      setData(await api.trends({ terms, scope: state.scope, exclude_imputed: state.reliableDates,
                                 exact: state.exact }))
      setState({ ...state, terms })
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  useEffect(() => { if (input.trim()) run() }, [])

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
        <label className="check" title="FES and PRIO carry year-precision dates only.">
          <input type="checkbox" checked={state.reliableDates}
                 onChange={(e) => setState({ ...state, reliableDates: e.target.checked })} />
          <span>Exclude imputed dates<br /><span className="muted">FES and PRIO</span></span>
        </label>
        <div className="notice" style={{ fontSize: '.79rem' }}>
          Rates are per 1,000 documents published that year. Annual output is not flat,
          so raw counts mislead.
        </div>
      </aside>

      <main className="content">
        <h2 style={{ fontSize: '1.5rem', marginBottom: 6 }}>Term frequency over time</h2>
        <p className="muted" style={{ fontSize: '.88rem', marginBottom: 16, maxWidth: '62ch' }}>
          Up to four terms, comma separated. 2026 is a partial year — its rate is comparable,
          its raw count is not.
        </p>
        <form className="searchrow" onSubmit={run}>
          <div className="searchbox">
            <input value={input} onChange={(e) => setInput(e.target.value)}
                   aria-label="Terms to chart" placeholder="e.g. enlargement, energy security, China" />
          </div>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Chart'}</button>
        </form>

        <Err error={error} />
        {busy && !data && <Empty><Spinner /> counting…</Empty>}
        {!busy && !data && <Empty>Enter one or more terms above to chart them.</Empty>}

        {data && (
          <>
            <div className="legend" style={{ marginTop: 22 }}>
              {data.series.map((s, i) => (
                <span className="key" key={s.term}>
                  <span className="sw" style={{ background: COLORS[i % 4] }} />{s.term}
                </span>
              ))}
            </div>
            <LineChart data={data} />
            <p className="muted" style={{ fontSize: '.82rem', margin: '10px 0 26px' }}>{data.note}</p>

            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Term</th>
                    {data.years.map((y) => <th key={y} className="num">{y}</th>)}
                    <th className="num">Documents</th>
                  </tr>
                </thead>
                <tbody>
                  {data.series.map((s, i) => (
                    <tr key={s.term}>
                      <td><span className="key"><span className="sw" style={{ background: COLORS[i % 4] }} />{s.term}</span></td>
                      {s.rates.map((r, j) => <td key={j} className="num tnum">{r.toFixed(1)}</td>)}
                      <td className="num tnum">{s.total.toLocaleString()}</td>
                    </tr>
                  ))}
                  <tr>
                    <td className="muted">documents that year</td>
                    {data.denominator.map((d, j) => <td key={j} className="num tnum muted">{d.toLocaleString()}</td>)}
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </>
  )
}

function LineChart({ data }) {
  const W = 720, H = 300, L = 46, R = 150, T = 16, B = 34
  const pw = W - L - R, ph = H - T - B
  const max = Math.max(10, ...data.series.flatMap((s) => s.rates)) * 1.12
  const x = (i) => L + (pw * i) / Math.max(data.years.length - 1, 1)
  const y = (v) => T + ph - (v / max) * ph
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f))

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 520, height: 'auto' }}
           role="img" aria-label={`Rate per 1,000 documents for ${data.series.map((s) => s.term).join(', ')}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={L + pw} y1={y(t)} y2={y(t)} stroke="var(--rule-soft)" />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize="11"
                  fontFamily="IBM Plex Mono, monospace" fill="var(--ink-3)">{t}</text>
          </g>
        ))}
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="var(--rule)" />
        {data.years.map((yr, i) => (
          <text key={yr} x={x(i)} y={H - 12} textAnchor="middle" fontSize="11"
                fontFamily="IBM Plex Mono, monospace" fill="var(--ink-3)">{yr}</text>
        ))}
        <text x={L} y={T - 3} fontSize="11" fontFamily="IBM Plex Mono, monospace"
              fill="var(--ink-3)">per 1,000 documents</text>
        {data.series.map((s, si) => (
          <g key={s.term}>
            <path fill="none" stroke={COLORS[si % 4]} strokeWidth="2" strokeLinejoin="round"
                  d={s.rates.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')} />
            {s.rates.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r="4" fill={COLORS[si % 4]}
                      stroke="var(--surface)" strokeWidth="2">
                <title>{`${data.years[i]} · ${s.term}: ${v.toFixed(1)} per 1,000 (${s.counts[i]} documents)`}</title>
              </circle>
            ))}
            <text x={L + pw + 10} y={y(s.rates[s.rates.length - 1]) + 4} fontSize="12"
                  fontWeight="600" fill={COLORS[si % 4]}>{s.term.slice(0, 20)}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}
