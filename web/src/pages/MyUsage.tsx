import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth'
import { Kpi } from '../components/ui'
import { api } from '../lib/api'
import { fmtCost, fmtMs, fmtNum, relTime } from '../lib/format'

type Usage = {
  kpis: {
    requests: number; cost: number; avg_latency: number | null
    input_tokens: number; output_tokens: number; error_rate: number; p95_ttft: number | null
  }
  recent_sessions: Array<{ id: string; title: string; updated_at: string; message_count: number }>
}

export default function MyUsage() {
  const { me } = useAuth()
  const { data } = useQuery({ queryKey: ['my-usage'], queryFn: () => api<Usage>('/insights/my/usage') })
  const k = data?.kpis

  return (
    <div>
      <h1 className="text-lg font-bold mb-1">My usage</h1>
      <div className="text-[12.5px] mb-4" style={{ color: 'var(--muted)' }}>
        Your personal footprint across all conversations · last 30 days
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3.5">
        <Kpi label="My requests" value={fmtNum(k?.requests)} sub="last 30 days" />
        <Kpi
          label="Tokens burned"
          value={k ? fmtNum(k.input_tokens + k.output_tokens) : '—'}
          sub={k ? `${fmtNum(k.input_tokens)} in · ${fmtNum(k.output_tokens)} out` : ' '}
        />
        <Kpi label="My cost" value={fmtCost(k?.cost)} sub={k && k.requests ? `${fmtCost(k.cost / k.requests)} / request` : ' '} />
        <Kpi label="Avg latency" value={fmtMs(k?.avg_latency)} sub={k?.p95_ttft ? `TTFT p95 ${fmtMs(k.p95_ttft)}` : ' '} />
      </div>
      <div className="card">
        <h3 className="text-[12.5px] font-semibold mb-3" style={{ color: 'var(--ink2)' }}>My conversations</h3>
        {(data?.recent_sessions ?? []).map(s => (
          <div key={s.id} className="flex justify-between gap-3 mb-2.5 text-[12.5px]">
            <span className="truncate" style={{ color: 'var(--ink2)' }}>{s.title || 'untitled conversation'}</span>
            <span className="tabular-nums shrink-0" style={{ color: 'var(--muted)' }}>
              {s.message_count} msgs · {relTime(s.updated_at)}
            </span>
          </div>
        ))}
        {data?.recent_sessions.length === 0 && (
          <div className="text-[12.5px]" style={{ color: 'var(--muted)' }}>No conversations yet — head to Chat.</div>
        )}
        {me?.role === 'member' && (
          <div className="text-[11px] mt-4" style={{ color: 'var(--muted)' }}>
            Full request traces & org-wide dashboards are admin-only.
          </div>
        )}
      </div>
    </div>
  )
}
