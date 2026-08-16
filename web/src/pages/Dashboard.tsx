import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import { fmtCost, fmtMs, fmtNum, fmtPct } from '../lib/format'
import { BarList, LatencyChart, RequestsChart, TokensChart, type Bucket } from '../components/charts'
import { Delta, Kpi, SectionTitle, Skeleton } from '../components/ui'

const RANGES: Array<[string, number]> = [['1h', 1], ['24h', 24], ['7d', 168], ['30d', 720]]

type Overview = {
  current: {
    requests: number; errors: number; cost: number; avg_latency: number | null
    error_rate: number; p95_ttft: number | null; streaming_pct: number
    input_tokens: number; output_tokens: number
  }
  previous: { requests: number; cost: number; error_rate: number }
}
type ModelRow = {
  provider: string; request_model: string; requests: number; cost: number
  avg_latency: number; avg_ttft: number | null; error_rate: number
}
type Risk = {
  pii_events: number; pii_entities: Array<[string, number]>
  aborted_streams: number; slo_breaches: number; tokens_estimated: number
}
type BudgetRow = { name: string; month_spend: number; budget: number | null; exceeded: boolean; warning: boolean }

export default function Dashboard() {
  const [hours, setHours] = useState(24)
  const overview = useQuery({
    queryKey: ['overview', hours],
    queryFn: () => api<Overview>(`/insights/overview?hours=${hours}`),
    refetchInterval: 15000,
  })
  const series = useQuery({
    queryKey: ['timeseries', hours],
    queryFn: () => api<{ buckets: Bucket[] }>(`/insights/timeseries?hours=${hours}`),
    refetchInterval: 30000,
  })
  const models = useQuery({
    queryKey: ['models', hours],
    queryFn: () => api<ModelRow[]>(`/insights/models?hours=${hours}`),
  })
  const errors = useQuery({
    queryKey: ['errors', hours],
    queryFn: () => api<Array<{ error_type: string; count: number }>>(`/insights/errors?hours=${hours}`),
  })
  const risk = useQuery({
    queryKey: ['risk', hours],
    queryFn: () => api<Risk>(`/insights/risk?hours=${hours}`),
  })
  const budgets = useQuery({ queryKey: ['budgets'], queryFn: () => api<BudgetRow[]>('/insights/budgets') })

  const cur = overview.data?.current
  const prev = overview.data?.previous
  const buckets = series.data?.buckets ?? []
  const alerting = (budgets.data ?? []).filter(b => b.warning || b.exceeded)

  return (
    <div>
      <div className="flex items-center gap-3 flex-wrap mb-1">
        <h1 className="text-lg font-bold m-0">Dashboard</h1>
        <div className="flex-1" />
        <div className="flex rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)', background: 'var(--surface2)' }}>
          {RANGES.map(([label, h]) => (
            <button
              key={label}
              onClick={() => setHours(h)}
              className="px-3 py-1.5 text-[12px] font-semibold border-0 cursor-pointer"
              style={{ background: h === hours ? 'var(--surface3)' : 'transparent', color: h === hours ? 'var(--ink)' : 'var(--muted)' }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="text-[12.5px] mb-4" style={{ color: 'var(--muted)' }}>
        Last {hours >= 24 ? `${hours / 24} day${hours > 24 ? 's' : ''}` : `${hours}h`} · all providers · refreshes live
      </div>

      {alerting.map(b => (
        <div
          key={b.name}
          className="card mb-3 !py-2.5 text-[12.5px] flex items-center gap-2"
          style={{ borderColor: b.exceeded ? 'var(--crit)' : 'var(--warn)' }}
        >
          <span>{b.exceeded ? '⛔' : '⚠️'}</span>
          Project <b>{b.name}</b> has spent {fmtCost(b.month_spend)} of its {fmtCost(b.budget)} monthly budget
          {b.exceeded ? ' — budget exceeded.' : ' (over 80%).'}
        </div>
      ))}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-3.5">
        <Kpi label="Requests" value={fmtNum(cur?.requests)} sub={cur && prev ? <Delta now={cur.requests} prev={prev.requests} /> : ' '} />
        <Kpi label="Total cost" value={fmtCost(cur?.cost)} sub={cur && prev ? <Delta now={cur.cost} prev={prev.cost} /> : ' '} />
        <Kpi label="Avg latency" value={fmtMs(cur?.avg_latency)} sub={cur ? `${fmtNum(cur.input_tokens + cur.output_tokens)} tokens` : ' '} />
        <Kpi label="p95 TTFT" value={fmtMs(cur?.p95_ttft)} sub={cur ? `streaming: ${fmtPct(cur.streaming_pct, 0)} of reqs` : ' '} />
        <Kpi label="Error rate" value={fmtPct(cur?.error_rate)} tone="error" sub={cur ? `${cur.errors} errors` : ' '} />
      </div>

      <div className="grid lg:grid-cols-2 gap-3 mb-3">
        <div className="card">
          <SectionTitle hint="per bucket, by outcome">Requests over time</SectionTitle>
          {series.isLoading ? <Skeleton h={170} /> : <RequestsChart data={buckets} />}
        </div>
        <div className="card">
          <SectionTitle hint="total request latency">Latency percentiles</SectionTitle>
          {series.isLoading ? <Skeleton h={170} /> : <LatencyChart data={buckets} />}
        </div>
      </div>
      <div className="grid lg:grid-cols-2 gap-3 mb-3">
        <div className="card">
          <SectionTitle hint="USD, by model">Cost by model</SectionTitle>
          {models.isLoading ? (
            <Skeleton h={150} />
          ) : (
            <BarList
              rows={(models.data ?? []).slice(0, 6).map(m => ({ name: m.request_model, value: m.cost }))}
              valueFormat={fmtCost}
            />
          )}
        </div>
        <div className="card">
          <SectionTitle hint="input vs output tokens">Token usage</SectionTitle>
          {series.isLoading ? <Skeleton h={170} /> : <TokensChart data={buckets} />}
        </div>
      </div>
      <div className="grid lg:grid-cols-[2fr_1fr] gap-3 mb-3">
        <div className="card">
          <SectionTitle hint="by provider error code">Top error types</SectionTitle>
          <BarList
            rows={(errors.data ?? []).map(e => ({ name: e.error_type, value: e.count }))}
            color="var(--crit)"
          />
          {(errors.data ?? []).length === 0 && !errors.isLoading && (
            <div className="text-[12px]" style={{ color: 'var(--muted)' }}>No errors in this window 🎉</div>
          )}
        </div>
        <div className="card">
          <SectionTitle hint="evidence summary">Risk signals</SectionTitle>
          {risk.data && (
            <BarList
              rows={[
                { name: 'PII masked', value: risk.data.pii_events },
                ...risk.data.pii_entities.slice(0, 3).map(([e, n]) => ({ name: `↳ ${e}`, value: n })),
                { name: 'Aborted streams', value: risk.data.aborted_streams },
                { name: 'SLO breaches >10s', value: risk.data.slo_breaches },
              ]}
              colors={['var(--s7)', 'var(--s7)', 'var(--s7)', 'var(--s7)', 'var(--serious)', 'var(--warn)']}
            />
          )}
        </div>
      </div>

      <div className="card overflow-x-auto">
        <SectionTitle hint="side-by-side comparison">Models</SectionTitle>
        <table className="tbl min-w-[640px]">
          <thead>
            <tr><th>Model</th><th>Provider</th><th className="text-right">Requests</th><th className="text-right">Cost</th><th className="text-right">Avg latency</th><th className="text-right">Avg TTFT</th><th className="text-right">Error rate</th></tr>
          </thead>
          <tbody>
            {(models.data ?? []).map(m => (
              <tr key={m.provider + m.request_model} style={{ cursor: 'default' }}>
                <td className="mono">{m.request_model}</td>
                <td style={{ color: 'var(--ink2)' }}>{m.provider}</td>
                <td className="text-right tabular-nums">{fmtNum(m.requests)}</td>
                <td className="text-right tabular-nums">{fmtCost(m.cost)}</td>
                <td className="text-right tabular-nums">{fmtMs(m.avg_latency)}</td>
                <td className="text-right tabular-nums">{fmtMs(m.avg_ttft)}</td>
                <td className="text-right tabular-nums" style={{ color: m.error_rate > 5 ? 'var(--errink)' : undefined }}>
                  {fmtPct(m.error_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
