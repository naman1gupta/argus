import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fmtCost } from '../lib/format'

export type Bucket = {
  bucket: string
  ok: number
  err: number
  p50: number | null
  p95: number | null
  p99: number | null
  tokens_in: number
  tokens_out: number
  cost: number
}

const tickStyle = { fontSize: 10.5, fill: 'var(--muted)' }
const hourTick = (iso: unknown) =>
  new Date(String(iso)).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })

const tooltipStyle = {
  background: 'var(--surface2)',
  border: '1px solid var(--border2)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--ink)',
}

export const Legend = ({ items }: { items: Array<[string, string]> }) => (
  <div className="flex gap-3.5 flex-wrap text-[11px] mb-1.5" style={{ color: 'var(--ink2)' }}>
    {items.map(([label, color]) => (
      <span key={label}>
        <i className="inline-block w-2.5 h-2.5 rounded-[3px] mr-1.5 align-[-1px]" style={{ background: color }} />
        {label}
      </span>
    ))}
  </div>
)

export function RequestsChart({ data }: { data: Bucket[] }) {
  return (
    <>
      <Legend items={[['success', 'var(--s1)'], ['error', 'var(--crit)']]} />
      <ResponsiveContainer width="100%" height={150}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -26, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={hourTick} tick={tickStyle} minTickGap={48} axisLine={false} tickLine={false} />
          <YAxis tick={tickStyle} axisLine={false} tickLine={false} width={54} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={hourTick} />
          <Area isAnimationActive={false} dataKey="ok" name="success" stroke="var(--s1)" strokeWidth={2} fill="var(--s1)" fillOpacity={0.18} />
          <Line isAnimationActive={false} dataKey="err" name="error" stroke="var(--crit)" strokeWidth={1.5} dot={false} />
          <Area isAnimationActive={false} dataKey="err" name="error" stroke="var(--crit)" strokeWidth={1.5} fill="none" />
        </AreaChart>
      </ResponsiveContainer>
    </>
  )
}

export function LatencyChart({ data }: { data: Bucket[] }) {
  return (
    <>
      <Legend items={[['p50', 'var(--seq250)'], ['p95', 'var(--seq450)'], ['p99', 'var(--seq650)']]} />
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={hourTick} tick={tickStyle} minTickGap={48} axisLine={false} tickLine={false} />
          <YAxis tick={tickStyle} axisLine={false} tickLine={false} width={58} tickFormatter={(v) => `${(Number(v) / 1000).toFixed(1)}s`} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={hourTick}
            formatter={(v) => [`${Math.round(Number(v))} ms`]}
          />
          <Line isAnimationActive={false} dataKey="p99" name="p99" stroke="var(--seq650)" strokeWidth={2} dot={false} connectNulls />
          <Line isAnimationActive={false} dataKey="p95" name="p95" stroke="var(--seq450)" strokeWidth={2} dot={false} connectNulls />
          <Line isAnimationActive={false} dataKey="p50" name="p50" stroke="var(--seq250)" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </>
  )
}

export function TokensChart({ data }: { data: Bucket[] }) {
  return (
    <>
      <Legend items={[['input', 'var(--s1)'], ['output', 'var(--s3)']]} />
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={hourTick} tick={tickStyle} minTickGap={48} axisLine={false} tickLine={false} />
          <YAxis tick={tickStyle} axisLine={false} tickLine={false} width={52} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={hourTick} />
          <Bar isAnimationActive={false} dataKey="tokens_in" name="input" stackId="t" fill="var(--s1)" radius={[0, 0, 0, 0]} />
          <Bar isAnimationActive={false} dataKey="tokens_out" name="output" stackId="t" fill="var(--s3)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </>
  )
}

export function BarList({
  rows,
  color = 'var(--s1)',
  colors,
  valueFormat = (v: number) => String(v),
}: {
  rows: Array<{ name: string; value: number }>
  color?: string
  colors?: string[]
  valueFormat?: (v: number) => string
}) {
  const max = Math.max(...rows.map(r => r.value), 1)
  return (
    <div>
      {rows.map((r, i) => (
        <div key={r.name} className="flex items-center gap-2.5 mb-2 text-[12.5px]">
          <span className="w-[150px] shrink-0 truncate" style={{ color: 'var(--ink2)' }} title={r.name}>
            {r.name}
          </span>
          <span
            className="h-3.5 rounded-r"
            style={{
              width: `${Math.max((r.value / max) * 55, 1)}%`,
              background: colors?.[i] ?? color,
            }}
          />
          <span className="tabular-nums" style={{ color: 'var(--muted)' }}>{valueFormat(r.value)}</span>
        </div>
      ))}
    </div>
  )
}

export const costFormat = fmtCost
