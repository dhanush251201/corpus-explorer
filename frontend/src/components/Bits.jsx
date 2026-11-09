import React from 'react'

export const Spinner = () => <span className="spin" aria-label="loading" />

export function Err({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="err" role="alert">
      <strong>{error}</strong>
      {onRetry && <> — <button className="btn ghost sm" onClick={onRetry}>retry</button></>}
    </div>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

export function Flags({ flags }) {
  if (!flags?.length) return null
  return (
    <div className="flags">
      {flags.map((f) => (
        <span key={f.id} className={`flag ${f.severity}`} title={f.detail}>
          {f.severity === 'critical' ? '▲' : f.severity === 'warning' ? '●' : '·'} {f.label}
        </span>
      ))}
    </div>
  )
}

/** Shows the exact Mongo query and how a natural-language input was read. */
export function QueryInspector({ result }) {
  if (!result) return null
  const interp = result.interpretation
  return (
    <details className="inspector">
      <summary>
        Query inspector — {result.collections?.length || 1} collection
        {(result.collections?.length || 1) > 1 ? 's' : ''}
        {interp?.used ? ` · interpreted by ${interp.used === 'llm' ? 'the model' : 'pattern matching'}` : ''}
      </summary>
      <div className="body">
        {interp?.explain?.length > 0 && (
          <div className="explain">
            {interp.explain.map((e, i) => (
              <div key={i}>
                <code>{e.clause}</code> = <b>{String(e.value)}</b>
                {e.note ? <span className="muted"> — {e.note}</span> : null}
              </div>
            ))}
          </div>
        )}
        {result.queries?.map((q, i) => (
          <div key={i}>
            <div className="muted mono" style={{ fontSize: '.72rem', marginTop: 10 }}>{q.collection}</div>
            <pre className="q">{JSON.stringify(q.filter, null, 2)}</pre>
          </div>
        ))}
        {result.truncated_merge && (
          <div className="notice">
            Deep paging across multiple collections is capped. Narrow the scope to a single
            institution for exhaustive paging.
          </div>
        )}
      </div>
    </details>
  )
}

export function KnowledgeWarning({ meta }) {
  const k = meta?.knowledge_check
  if (!k || k.ok !== false) return null
  return (
    <div className="err" role="status" style={{ margin: '14px 24px 0' }}>
      <strong>{k.live_sources - k.described_in_file} source(s) have no metadata.</strong>{' '}
      They are listed and searchable, but without document counts or coverage dates.{' '}
      {k.file?.includes('fixtures')
        ? <>The app is reading <code>{k.file}</code> — that is the demo fixture. Restart
           without <code>KNOWLEDGE_PATH</code> set.</>
        : <>Missing: {(k.undescribed || []).slice(0, 5).join(', ')}.</>}
    </div>
  )
}

export function ReadOnlyBadge({ meta }) {
  if (!meta) return null
  const conn = meta.read_only?.connection || {}
  const warn = conn.write_capable === true
  const tip = warn
    ? `WARNING: this connection holds write-capable roles (${(conn.writable_roles || []).join(', ')}). ` +
      'The app never writes, but you should switch to a user with only the `read` role.'
    : [...(meta.read_only?.layers || []), conn.note].filter(Boolean).join('\n')
  return (
    <span className={`ro-badge${warn ? ' warn' : ''}`} title={tip}>
      {warn ? '▲ read-only app · write-capable key' : '● read only'}
    </span>
  )
}
