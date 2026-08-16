import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { clockTime, fmtCost, fmtMs, fmtNum, shortId } from '../lib/format'
import { Chip, Masked, StatusPill } from './ui'

export type LogRow = {
  id: string
  generation_id: string
  session_id: string
  end_user_id: string
  provider: string
  request_model: string
  response_model: string
  operation: string
  is_streaming: boolean
  status: string
  error_type: string
  error_message: string
  started_at: string
  first_chunk_at: string | null
  completed_at: string | null
  latency_ms: number | null
  ttft_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  cached_tokens: number | null
  reasoning_tokens: number | null
  tokens_estimated: boolean
  cost_usd: string | number | null
  finish_reasons: string[]
  request_params: Record<string, unknown>
  prompt_preview: string
  response_preview: string
  pii_masked: boolean
  pii_entities_found: string[]
  environment: string
}

function Waterfall({ row }: { row: LogRow }) {
  const total = row.latency_ms ?? 0
  const ttft = row.ttft_ms ?? 0
  if (!total) return null
  const p = (v: number) => `${Math.min((v / total) * 94, 94)}%`
  const seg = (label: string, left: string, width: string, color: string, value: string) => (
    <div className="flex items-center gap-2.5 mb-1.5 text-[11.5px]">
      <span className="w-[120px] shrink-0" style={{ color: 'var(--ink2)' }}>{label}</span>
      <div className="flex-1 h-4 relative rounded" style={{ background: 'var(--surface2)' }}>
        <div className="absolute top-0.5 bottom-0.5 rounded-[3px]" style={{ left, width, background: color }} />
      </div>
      <span className="w-[70px] text-right tabular-nums shrink-0" style={{ color: 'var(--muted)' }}>{value}</span>
    </div>
  )
  return (
    <div>
      {ttft > 0 && seg('Time to first token', '0%', p(ttft), 'var(--seq250)', fmtMs(ttft))}
      {ttft > 0 && seg('Streaming', p(ttft), p(total - ttft), 'var(--seq450)', fmtMs(total - ttft))}
      {seg('Total', '0%', '94%', 'linear-gradient(90deg,var(--seq250),var(--s7))', fmtMs(total))}
    </div>
  )
}

const Sect = ({ title, right }: { title: string; right?: React.ReactNode }) => (
  <div className="text-[11px] uppercase tracking-[0.6px] font-bold mt-4 mb-2 flex items-center" style={{ color: 'var(--muted)' }}>
    {title}
    {right && <span className="ml-auto normal-case font-medium tracking-normal">{right}</span>}
  </div>
)

export default function LogDrawer({ generationId, onClose }: { generationId: string; onClose: () => void }) {
  const { data: row } = useQuery({
    queryKey: ['log', generationId],
    queryFn: () => api<LogRow>(`/insights/logs/${generationId}`),
  })

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ background: 'rgba(0,0,0,.5)' }} onClick={onClose} />
      <div
        className="fixed right-0 top-0 bottom-0 z-50 w-full sm:w-[620px] flex flex-col border-l overflow-hidden"
        style={{ background: 'var(--surface)', borderColor: 'var(--border2)', boxShadow: '-30px 0 70px rgba(0,0,0,.45)' }}
      >
        <header className="flex items-center gap-2.5 px-5 py-4 border-b" style={{ borderColor: 'var(--border)' }}>
          {row && <StatusPill status={row.status} />}
          <button
            className="mono cursor-pointer bg-transparent border-0"
            title="copy generation id"
            onClick={() => navigator.clipboard.writeText(generationId)}
          >
            {shortId(generationId, 16)} ⧉
          </button>
          {row && (
            <span className="text-[11.5px]" style={{ color: 'var(--muted)' }}>
              {new Date(row.started_at).toLocaleString()}
            </span>
          )}
          <button className="ml-auto text-lg bg-transparent border-0 cursor-pointer" style={{ color: 'var(--muted)' }} onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!row ? (
            <div className="skeleton h-40" />
          ) : (
            <>
              <div className="flex gap-2 flex-wrap mb-2">
                <Chip label="provider" value={row.provider} />
                <Chip label="model" value={row.request_model} />
                {row.end_user_id && <Chip label="user" value={row.end_user_id} />}
                <Chip label="streaming" value={row.is_streaming ? 'yes' : 'no'} />
                {row.session_id && <Chip label="session" value={shortId(row.session_id)} />}
                <Chip label="env" value={row.environment} />
                {Object.entries(row.request_params ?? {}).map(([k, v]) => (
                  <Chip key={k} label={k} value={String(v)} />
                ))}
              </div>

              {row.status === 'error' && (
                <div className="card !p-3 mb-2 text-[12.5px]" style={{ borderColor: 'var(--crit)' }}>
                  <b style={{ color: 'var(--errink)' }}>{row.error_type}</b>
                  <div style={{ color: 'var(--ink2)' }}>{row.error_message}</div>
                </div>
              )}

              <Sect title="Timing" />
              <Waterfall row={row} />

              <Sect title="Usage & cost" right={row.tokens_estimated ? <span style={{ color: 'var(--warn)' }}>usage estimated (stream aborted)</span> : undefined} />
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  ['input tok', fmtNum(row.input_tokens)],
                  ['output tok', fmtNum(row.output_tokens)],
                  ['cached tok', fmtNum(row.cached_tokens)],
                  ['cost', fmtCost(row.cost_usd == null ? null : Number(row.cost_usd))],
                ].map(([label, value]) => (
                  <div key={label as string} className="rounded-lg px-2.5 py-2" style={{ background: 'var(--surface2)' }}>
                    <div className="text-[10px] uppercase" style={{ color: 'var(--muted)' }}>{label}</div>
                    <div className="text-[15px] font-bold tabular-nums">{value}</div>
                  </div>
                ))}
              </div>

              <Sect
                title="Prompt preview"
                right={
                  row.pii_masked ? (
                    <span style={{ color: 'var(--s7)' }}>
                      🛡 {row.pii_entities_found.length} PII entit{row.pii_entities_found.length === 1 ? 'y' : 'ies'} masked client-side
                    </span>
                  ) : undefined
                }
              />
              <div className="card !p-3 text-[12.5px]" style={{ color: 'var(--ink2)' }}>
                {row.prompt_preview ? <Masked text={row.prompt_preview} /> : <i>content logging disabled</i>}
              </div>

              <Sect title="Response preview" />
              <div className="card !p-3 text-[12.5px]" style={{ color: 'var(--ink2)' }}>
                {row.response_preview ? <Masked text={row.response_preview} /> : <i>—</i>}
              </div>

              <Sect
                title="Raw record"
                right={
                  <span className="mono">
                    {row.finish_reasons.length > 0 && `finish: ${row.finish_reasons.join(',')} · `}
                    {clockTime(row.started_at)}
                  </span>
                }
              />
              <pre
                className="rounded-lg border p-3 overflow-x-auto text-[11px] leading-relaxed"
                style={{ background: 'var(--page)', borderColor: 'var(--border)', color: 'var(--ink2)', fontFamily: 'var(--mono)' }}
              >
                {JSON.stringify(row, null, 2)}
              </pre>
            </>
          )}
        </div>
      </div>
    </>
  )
}
