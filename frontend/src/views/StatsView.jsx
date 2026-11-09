import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, Err, Empty } from '../components/Bits'

const n = (v) => (v ?? 0).toLocaleString()

export default function StatsView({ state, setState }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () => api.stats().then(setData).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  // While a recompute is in flight, poll until it lands.
  useEffect(() => {
    if (!data?.running) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [data?.running])

  const refresh = async () => {
    setBusy(true)
    try { await api.refreshStats(); await load() }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  const s = data?.snapshot
  const openDoc = (url) => setState({ ...state, tab: 'search', doc: url, scope: 'all' })

  return (
    <>
      <aside className="side">
        <div className="sidehead">Snapshot</div>
        {s ? (
          <>
            <dl className="kv" style={{ margin: '0 0 16px' }}>
              <dt>Computed</dt><dd>{new Date(s.generated).toLocaleString()}</dd>
              <dt>Took</dt><dd className="tnum">{s.duration_sec}s</dd>
              <dt>Covers</dt><dd>{n(s.totals.documents)} documents</dd>
            </dl>
            {data.stale && <div className="notice" style={{ fontSize: '.79rem' }}>
              This snapshot predates the most recent Sunday. A refresh runs automatically.
            </div>}
          </>
        ) : <p className="muted" style={{ fontSize: '.85rem' }}>No snapshot yet.</p>}

        <button className="btn ghost sm" onClick={refresh} disabled={busy || data?.running}
                style={{ width: '100%', marginBottom: 14 }}>
          {data?.running ? <><Spinner /> computing…</> : busy ? <Spinner /> : 'Recompute now'}
        </button>

        <div className="sidehead">How this works</div>
        <p className="muted" style={{ fontSize: '.79rem', lineHeight: 1.5 }}>
          Counting every word in the corpus takes minutes, so these figures are computed
          weekly — each Sunday — and cached. The cluster is read only: the snapshot is
          written to local disk, never back to MongoDB.
        </p>
        {s?.notes?.length > 0 && (
          <>
            <div className="sidehead">Notes</div>
            <p className="muted" style={{ fontSize: '.76rem', lineHeight: 1.5 }}>
              {s.notes.length} source{s.notes.length === 1 ? '' : 's'} used the slower
              fallback path.
            </p>
            <details>
              <summary className="muted" style={{ fontSize: '.74rem', cursor: 'pointer' }}>details</summary>
              {s.notes.slice(0, 4).map((x, i) => (
                <p key={i} className="muted" style={{ fontSize: '.7rem', wordBreak: 'break-word' }}>
                  {x.length > 120 ? x.slice(0, 120) + '…' : x}
                </p>
              ))}
            </details>
          </>
        )}
      </aside>

      <main className="content">
        <h2 style={{ fontSize: '1.5rem', marginBottom: 6 }}>Statistics</h2>
        <p className="muted" style={{ fontSize: '.88rem', marginBottom: 20, maxWidth: '64ch' }}>
          Measured across every source. Article length means the web article where there is
          one, falling back to the PDF — the same rule the reader uses, so these numbers
          match what you see on a document.
        </p>

        <Err error={error} />
        {!s && !error && (
          <Empty>
            <Spinner /> {data?.running ? 'computing the first snapshot — this scans every document'
                                       : 'loading…'}
          </Empty>
        )}

        {s && (
          <>
            <div className="tiles">
              <Tile label="Documents" value={n(s.totals.documents)} sub={`${s.totals.sources} sources`} />
              <Tile label="Total words" value={fmtBig(s.totals.words_effective)}
                    sub={`${n(s.length.mean)} mean · ${n(s.length.median)} median`} />
              <Tile label="Distinct authors" value={n(s.totals.distinct_authors)}
                    sub={`${s.totals.mean_authors_per_doc} per document`} />
              <Tile label="Covers" value={(s.totals.first_published || '').slice(0, 4) + '–' +
                    (s.totals.last_published || '').slice(0, 4)}
                    sub={`${s.totals.first_published} to ${s.totals.last_published}`} />
            </div>

            <h3 style={{ fontSize: '1.15rem', margin: '34px 0 4px' }}>Longest and shortest</h3>
            <p className="muted" style={{ fontSize: '.85rem', marginBottom: 14, maxWidth: '64ch' }}>
              The shortest documents are usually not articles at all — staff pages, stubs and
              placeholders — so the genuinely shortest publication is listed separately.
            </p>
            <div className="extremes">
              <Extreme title="Longest" rows={s.length.longest} onOpen={openDoc} />
              <Extreme title="Shortest" rows={s.length.shortest} onOpen={openDoc}
                       note="any non-empty document" />
              <Extreme title={`Shortest over ${s.length.short_doc_threshold} words`}
                       rows={s.length.shortest_real} onOpen={openDoc} note="likely a real publication" />
            </div>

            <h3 style={{ fontSize: '1.15rem', margin: '34px 0 14px' }}>Length distribution</h3>
            <Histogram hist={s.length.histogram} total={s.totals.documents} />
            <div className="tiles small" style={{ marginTop: 14 }}>
              {[['10th percentile', s.length.p10], ['median', s.length.median],
                ['90th percentile', s.length.p90], ['99th percentile', s.length.p99]].map(([l, v]) => (
                <Tile key={l} label={l} value={n(v)} sub="words" />
              ))}
            </div>

            <h3 style={{ fontSize: '1.15rem', margin: '34px 0 14px' }}>Documents per year</h3>
            <Bars data={Object.entries(s.by_year).map(([k, v]) => [k, v])} />

            <h3 style={{ fontSize: '1.15rem', margin: '34px 0 4px' }}>Data quality</h3>
            <p className="muted" style={{ fontSize: '.85rem', marginBottom: 14 }}>
              Counts of documents carrying each known problem.
            </p>
            <div className="tablewrap">
              <table className="data">
                <tbody>
                  {[['No usable article text — PDF only', s.quality.no_article_text],
                    ['No PDF text', s.quality.no_pdf_text],
                    [`Under ${s.length.short_doc_threshold} words`, s.quality.short_documents],
                    ['No text at all', s.quality.empty_documents],
                    ['Year-precision dates only (FES, PRIO)', s.quality.imputed_dates],
                    ['Unusable titles (SWP)', s.quality.broken_titles],
                    ['Outside the legacy master collection', s.quality.outside_master],
                    ['No author listed', s.totals.documents_without_author]].map(([l, v]) => (
                    <tr key={l}>
                      <td>{l}</td>
                      <td className="num tnum" style={{ width: 110 }}>{n(v)}</td>
                      <td className="num tnum muted" style={{ width: 70 }}>
                        {((v / s.totals.documents) * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3 style={{ fontSize: '1.15rem', margin: '34px 0 14px' }}>By source</h3>
            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr><th>Source</th><th className="num">Documents</th><th className="num">Words</th>
                      <th className="num">Mean</th><th className="num">Median</th>
                      <th className="num">Longest</th><th>Covers</th></tr>
                </thead>
                <tbody>
                  {s.by_source.map((r) => (
                    <tr key={r.collection} style={{ cursor: 'pointer' }}
                        onClick={() => setState({ ...state, tab: 'search', scope: r.name, q: '' })}>
                      <td><b style={{ color: 'var(--ink)' }}>{r.name}</b>
                        {r.imputed_dates && <span className="flag critical" style={{ marginLeft: 7 }}>dates imputed</span>}</td>
                      <td className="num tnum">{n(r.documents)}</td>
                      <td className="num tnum">{fmtBig(r.words)}</td>
                      <td className="num tnum">{n(r.mean_words)}</td>
                      <td className="num tnum">{n(r.median_words)}</td>
                      <td className="num tnum">{n(r.max_words)}</td>
                      <td className="tnum" style={{ whiteSpace: 'nowrap' }}>{r.first} → {r.last}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))',
                          gap: 22, marginTop: 34 }}>
              <div>
                <h3 style={{ fontSize: '1.15rem', marginBottom: 14 }}>Most prolific authors</h3>
                <div className="tablewrap">
                  <table className="data">
                    <tbody>
                      {s.top_authors.slice(0, 12).map((a) => (
                        <tr key={a.name} style={{ cursor: 'pointer' }}
                            onClick={() => setState({ ...state, tab: 'search', author: a.name, scope: 'all', q: '' })}>
                          <td>{a.name}</td>
                          <td className="num tnum" style={{ width: 80 }}>{n(a.documents)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted" style={{ fontSize: '.78rem', marginTop: 8 }}>
                  Names are unnormalised — the same person may appear more than once.
                </p>
              </div>
              <div>
                <h3 style={{ fontSize: '1.15rem', marginBottom: 14 }}>Document types</h3>
                <div className="tablewrap">
                  <table className="data">
                    <tbody>
                      {s.by_type.slice(0, 12).map((t) => (
                        <tr key={t.name}>
                          <td>{t.name}</td>
                          <td className="num tnum" style={{ width: 80 }}>{n(t.documents)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <p className="muted" style={{ fontSize: '.78rem', marginTop: 30 }}>
              Snapshot taken {new Date(s.generated).toLocaleString()} in {s.duration_sec}s ·
              next automatic refresh after {new Date(data.next_refresh_after).toLocaleDateString()} ·
              stored at <code>{data.storage}</code>
            </p>
          </>
        )}
      </main>
    </>
  )
}

const fmtBig = (v) => v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? Math.round(v / 1e3) + 'k' : String(v ?? 0)

function Tile({ label, value, sub }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value tnum">{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  )
}

function Extreme({ title, rows, note, onOpen }) {
  if (!rows?.length) return null
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="tile-label" style={{ marginBottom: 2 }}>{title}</div>
      {note && <div className="muted" style={{ fontSize: '.74rem', marginBottom: 10 }}>{note}</div>}
      {rows.slice(0, 3).map((d, i) => (
        <div key={d.url + i} className="extreme-row" onClick={() => onOpen(d.url)}
             tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(d.url)}>
          <div className="tnum extreme-w">{n(d.words)}<span className="muted"> w</span></div>
          <div style={{ minWidth: 0 }}>
            <div className="extreme-title">{d.title}</div>
            <div className="muted" style={{ fontSize: '.74rem' }}>
              {d.source}{d.published_at ? ` · ${d.published_at}` : ''}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** Single series, so no legend: the heading names it. */
function Histogram({ hist, total }) {
  const max = Math.max(1, ...hist.map((h) => h.count))
  return (
    <div className="chart">
      {hist.filter((h) => h.count > 0).map((h) => {
        const label = h.to == null ? `${n(h.from)}+` : h.from === 0 ? '0' : `${n(h.from)}–${n(h.to)}`
        return (
          <div className="row" key={label}
               title={`${n(h.count)} documents (${((h.count / total) * 100).toFixed(1)}%)`}>
            <span className="name tnum">{label}</span>
            <span className="track"><span className="bar" style={{ width: `${(h.count / max) * 100}%` }} /></span>
            <span className="val">{n(h.count)}</span>
          </div>
        )
      })}
    </div>
  )
}

function Bars({ data }) {
  const max = Math.max(1, ...data.map(([, v]) => v))
  return (
    <div className="chart">
      {data.map(([k, v]) => (
        <div className="row" key={k} title={`${k}: ${n(v)} documents`}>
          <span className="name tnum">{k}</span>
          <span className="track"><span className="bar" style={{ width: `${(v / max) * 100}%` }} /></span>
          <span className="val">{n(v)}</span>
        </div>
      ))}
    </div>
  )
}
