import type { ReactNode } from 'react'
import { maskedParts } from '../lib/format'

export const StatusPill = ({ status }: { status: string }) => (
  <span className={`pill ${status}`}>{status}</span>
)

export const Chip = ({ label, value }: { label: string; value: ReactNode }) => (
  <span className="chip">
    {label} <b>{value}</b>
  </span>
)

export function Masked({ text }: { text: string }) {
  return (
    <>
      {maskedParts(text).map((p, i) =>
        p.token ? (
          <span key={i} className="masktok">
            {p.text.replace('<', '‹').replace('>', '›')}
          </span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  )
}

const PROVIDER_COLORS: Record<string, string> = {
  anthropic: 'var(--s1)',
  'gcp.gemini': 'var(--s2)',
  groq: 'var(--s3)',
  openai: 'var(--s4)',
  mock: 'var(--s7)',
  other: 'var(--muted)',
}

export const ProviderDot = ({ provider }: { provider: string }) => (
  <i
    className="inline-block w-2 h-2 rounded-[2.5px] mr-2 align-baseline"
    style={{ background: PROVIDER_COLORS[provider] ?? 'var(--muted)' }}
  />
)

export function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'error'
}) {
  return (
    <div className="card">
      <div className="text-[10.5px] font-bold uppercase tracking-[0.6px]" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div
        className="text-[25px] font-bold tracking-tight tabular-nums my-0.5"
        style={tone === 'error' ? { color: 'var(--errink)' } : undefined}
      >
        {value}
      </div>
      {sub && <div className="text-[11.5px]" style={{ color: 'var(--muted)' }}>{sub}</div>}
    </div>
  )
}

export const Delta = ({ now, prev, invert }: { now: number; prev: number; invert?: boolean }) => {
  if (!prev) return null
  const pct = ((now - prev) / prev) * 100
  const good = invert ? pct <= 0 : pct >= 0
  return (
    <span style={{ color: good ? 'var(--goodink)' : 'var(--errink)' }}>
      {pct >= 0 ? '▲' : '▼'} {Math.abs(pct).toFixed(1)}%
    </span>
  )
}

export const Skeleton = ({ h = 120 }: { h?: number }) => (
  <div className="skeleton w-full" style={{ height: h }} />
)

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-2.5">
      <h3 className="text-[12.5px] font-semibold m-0" style={{ color: 'var(--ink2)' }}>
        {children}
      </h3>
      {hint && <div className="text-[11px]" style={{ color: 'var(--muted)' }}>{hint}</div>}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="py-10 text-center text-[12.5px]" style={{ color: 'var(--muted)' }}>
      {children}
    </div>
  )
}
