import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { LogRow } from '../components/LogDrawer'
import LogDrawer from '../components/LogDrawer'
import { Masked, StatusPill } from '../components/ui'
import { api } from '../lib/api'
import { fmtCost, fmtMs, fmtNum, relTime, shortId } from '../lib/format'

type SessionAgg = {
  session_id: string; title: string; requests: number; errors: number
  cost: number; tokens: number; avg_latency: number; last_at: string; end_user_id: string
}
type Replay = {
  session_id: string; title: string
  messages: Array<{ id: string; role: string; content: string; provider: string; model: string; seq: number }>
  logs: LogRow[]
}

export default function Sessions() {
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string | null>(null)
  const [traceId, setTraceId] = useState<string | null>(null)

  const sessions = useQuery({
    queryKey: ['insight-sessions'],
    queryFn: () => api<SessionAgg[]>('/insights/sessions?hours=720'),
  })
  const active = selected ?? sessions.data?.[0]?.session_id ?? null
  const replay = useQuery({
    queryKey: ['replay', active],
    queryFn: () => api<Replay>(`/insights/sessions/${active}`),
    enabled: !!active,
  })

  const agg = (sessions.data ?? []).find(s => s.session_id === active)
  const logsBySeq = replay.data?.logs ?? []
  let assistantIdx = -1

  return (
    <div className="h-full flex flex-col">
      <h1 className="text-lg font-bold mb-1">Sessions</h1>
      <div className="text-[12.5px] mb-3.5" style={{ color: 'var(--muted)' }}>
        Multi-turn conversations grouped by session id — replay any conversation with per-turn telemetry.
      </div>
      <div className="flex-1 min-h-0 grid lg:grid-cols-[340px_1fr] gap-3.5">
        <div className="card !p-0 overflow-y-auto">
          {(sessions.data ?? []).map(s => (
            <button
              key={s.session_id}
              onClick={() => setSelected(s.session_id)}
              className="w-full text-left px-3.5 py-3 border-b border-0 cursor-pointer block"
              style={{
                background: s.session_id === active ? 'var(--surface3)' : 'transparent',
                borderBottom: '1px solid var(--grid)',
                boxShadow: s.session_id === active ? 'inset 3px 0 0 var(--s1)' : undefined,
                color: 'inherit',
              }}
            >
              <div className="font-semibold text-[13px] mb-0.5 truncate">
                {s.title || <span className="mono">{shortId(s.session_id, 12)}</span>}
              </div>
              <div className="flex gap-2.5 text-[11.5px] flex-wrap" style={{ color: 'var(--muted)' }}>
                <span>{s.requests} calls</span>
                <span>{fmtCost(s.cost)}</span>
                <span>{fmtNum(s.tokens)} tok</span>
                {s.errors > 0 && <span style={{ color: 'var(--errink)' }}>{s.errors} errors</span>}
                <span className="ml-auto">{relTime(s.last_at)}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="card !p-0 flex flex-col min-h-0">
          <div className="flex gap-3 items-center px-4 py-3 border-b flex-wrap text-[12px]" style={{ borderColor: 'var(--border)', color: 'var(--ink2)' }}>
            <button className="mono bg-transparent border-0 cursor-pointer" onClick={() => active && navigator.clipboard.writeText(active)}>
              {active ? shortId(active, 12) : '—'} ⧉
            </button>
            {agg && (
              <>
                <span><b>{agg.requests}</b> calls</span>
                <span><b>{fmtNum(agg.tokens)}</b> tokens</span>
                <span><b>{fmtCost(agg.cost)}</b></span>
                <span>avg <b>{fmtMs(agg.avg_latency)}</b></span>
                {agg.errors === 0 ? <StatusPill status="success" /> : <span className="pill error">{agg.errors} errors</span>}
              </>
            )}
            {active && (
              <a className="chip ml-auto no-underline cursor-pointer" href={`/api/v1/insights/sessions/${active}/evidence.csv`}>
                ⬇ export evidence CSV
              </a>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {replay.data?.messages.length ? (
              replay.data.messages.map(m => {
                if (m.role === 'assistant') assistantIdx += 1
                const log = m.role === 'assistant' ? logsBySeq[assistantIdx] : undefined
                return m.role === 'user' ? (
                  <div key={m.id} className="bubble u-msg mb-3.5"><Masked text={m.content} /></div>
                ) : (
                  <div key={m.id} className="mb-3.5">
                    <div className="bubble a-msg"><Masked text={m.content} /></div>
                    <div className="flex gap-1.5 mt-1 flex-wrap text-[10.5px]" style={{ color: 'var(--muted)' }}>
                      {m.model && <span className="chip !py-0.5">{m.model}</span>}
                      {log && (
                        <>
                          <span className="chip !py-0.5">TTFT {fmtMs(log.ttft_ms)}</span>
                          <span className="chip !py-0.5">{fmtMs(log.latency_ms)}</span>
                          <span className="chip !py-0.5">{log.input_tokens} → {log.output_tokens} tok</span>
                          {log.pii_masked && <span className="chip !py-0.5" style={{ color: 'var(--s7)' }}>🛡 {log.pii_entities_found.length} masked</span>}
                          <button className="chip !py-0.5 cursor-pointer" style={{ color: 'var(--s1)' }} onClick={() => setTraceId(log.generation_id)}>
                            view trace →
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="text-center py-10 text-[12.5px]" style={{ color: 'var(--muted)' }}>
                {replay.isLoading ? 'Loading…' : (
                  <>
                    No chat transcript stored for this session (telemetry-only, e.g. seeded demo data or an external SDK consumer).
                    <div className="mt-2">
                      <button className="btn-ghost" onClick={() => navigate(`/requests`)}>view its requests instead</button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      {traceId && <LogDrawer generationId={traceId} onClose={() => setTraceId(null)} />}
    </div>
  )
}
