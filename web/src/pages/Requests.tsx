import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import LogDrawer, { type LogRow } from '../components/LogDrawer'
import { Masked, ProviderDot, StatusPill } from '../components/ui'
import { api } from '../lib/api'
import { clockTime, fmtCost, fmtMs, shortId } from '../lib/format'

type LiveEvent = {
  project_id: string
  event_id: string
  type: 'generation-start' | 'generation-end'
  body: Record<string, unknown>
}

const PROVIDERS = ['anthropic', 'gcp.gemini', 'groq', 'openai', 'mock']
const STATUSES = ['success', 'error', 'pending', 'aborted']

export default function Requests() {
  const navigate = useNavigate()
  const { generationId } = useParams()
  const [provider, setProvider] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [qDebounced, setQDebounced] = useState('')
  const [live, setLive] = useState<Array<{ id: string; body: Record<string, unknown>; phase: string }>>([])
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 350)
    return () => clearTimeout(t)
  }, [q])

  const logs = useQuery({
    queryKey: ['logs', provider, status, qDebounced],
    queryFn: () =>
      api<{ rows: LogRow[] }>(
        `/insights/logs?hours=168&limit=50&provider=${provider}&status=${status}&q=${encodeURIComponent(qDebounced)}`,
      ),
    refetchInterval: 10000,
  })

  // Live tail: SSE straight off the Kafka topic. Start events appear as
  // pending rows; end events resolve them in place.
  useEffect(() => {
    const es = new EventSource('/api/v1/insights/tail')
    esRef.current = es
    es.addEventListener('log', e => {
      const ev = JSON.parse((e as MessageEvent).data) as LiveEvent
      const gid = ev.body.generation_id as string
      setLive(prev => {
        if (ev.type === 'generation-end') {
          const existing = prev.find(r => r.body.generation_id === gid)
          if (existing) {
            return prev.map(r =>
              r.body.generation_id === gid
                ? { ...r, body: { ...r.body, ...ev.body }, phase: 'end' }
                : r,
            )
          }
          return [{ id: ev.event_id, body: ev.body, phase: 'end' }, ...prev].slice(0, 8)
        }
        return [{ id: ev.event_id, body: ev.body, phase: 'start' }, ...prev].slice(0, 8)
      })
    })
    return () => es.close()
  }, [])

  const open = (gid: string) => navigate(`/requests/${gid}`)

  return (
    <div>
      <h1 className="text-lg font-bold mb-1">Requests</h1>
      <div className="text-[12.5px] mb-4" style={{ color: 'var(--muted)' }}>
        Every LLM inference call, streamed in near-real-time. Click a row for full detail — each row has a shareable URL.
      </div>
      <div className="flex gap-2 flex-wrap items-center mb-3">
        <select className="input" value={provider} onChange={e => setProvider(e.target.value)}>
          <option value="">Provider: all</option>
          {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select className="input" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">Status: all</option>
          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          className="input w-full sm:w-[260px]"
          placeholder="Search preview, session, generation id…"
          value={q}
          onChange={e => setQ(e.target.value)}
        />
        <div className="ml-auto flex items-center gap-2 text-[12px] font-semibold" style={{ color: 'var(--good)' }}>
          <span className="pulse-dot" /> LIVE
        </div>
      </div>

      {live.length > 0 && (
        <div className="card !p-0 mb-3 overflow-x-auto">
          <div className="px-3 pt-2.5 pb-1 text-[10.5px] uppercase tracking-[0.5px] font-bold" style={{ color: 'var(--good)' }}>
            Live tail — straight off the Kafka topic
          </div>
          <table className="tbl min-w-[760px]">
            <tbody>
              {live.map(r => (
                <tr
                  key={String(r.body.generation_id)}
                  className="flash"
                  onClick={() => r.phase === 'end' && open(String(r.body.generation_id))}
                >
                  <td className="mono w-[86px]">{r.body.started_at ? clockTime(String(r.body.started_at)) : 'now'}</td>
                  <td className="w-[100px]"><StatusPill status={r.phase === 'start' ? 'pending' : String(r.body.status ?? 'success')} /></td>
                  <td>
                    <ProviderDot provider={String(r.body.provider ?? '')} />
                    <span className="mono">{String(r.body.request_model ?? r.body.response_model ?? '')}</span>
                  </td>
                  <td className="max-w-[300px] truncate" style={{ color: 'var(--ink2)' }}>
                    <Masked text={String(r.body.prompt_preview ?? r.body.response_preview ?? '')} />
                  </td>
                  <td className="text-right tabular-nums">
                    {r.body.latency_ms != null ? fmtMs(Number(r.body.latency_ms)) : '…'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card !p-0 overflow-x-auto">
        <table className="tbl min-w-[900px]">
          <thead>
            <tr>
              <th>Time</th><th>Status</th><th>Provider / model</th><th>Preview</th><th>User</th>
              <th className="text-right">Tokens</th><th className="text-right">Cost</th>
              <th className="text-right">TTFT</th><th className="text-right">Latency</th><th>Session</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data?.rows ?? []).map(r => (
              <tr key={r.id} onClick={() => open(r.generation_id)}>
                <td className="mono">{clockTime(r.started_at)}</td>
                <td><StatusPill status={r.status} /></td>
                <td><ProviderDot provider={r.provider} /><span className="mono">{r.request_model}</span></td>
                <td className="max-w-[320px] truncate" style={{ color: 'var(--ink2)' }}>
                  <Masked text={r.prompt_preview} />
                </td>
                <td style={{ color: 'var(--ink2)' }}>{r.end_user_id || '—'}</td>
                <td className="text-right tabular-nums">
                  {r.input_tokens != null ? `${r.input_tokens} → ${r.output_tokens}` : '—'}
                </td>
                <td className="text-right tabular-nums">{fmtCost(r.cost_usd == null ? null : Number(r.cost_usd))}</td>
                <td className="text-right tabular-nums">{fmtMs(r.ttft_ms)}</td>
                <td className="text-right tabular-nums">{fmtMs(r.latency_ms)}</td>
                <td className="mono" style={{ color: 'var(--s1)' }}>{r.session_id ? shortId(r.session_id) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.isLoading && <div className="skeleton h-48 m-3" />}
      </div>

      {generationId && <LogDrawer generationId={generationId} onClose={() => navigate('/requests')} />}
    </div>
  )
}
