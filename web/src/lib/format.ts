export const fmtNum = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString()

export const fmtCost = (n: number | null | undefined) => {
  if (n == null) return '—'
  if (n === 0) return '$0'
  if (n < 0.01) return '$' + n.toFixed(4)
  return '$' + n.toFixed(2)
}

export const fmtMs = (n: number | null | undefined) => {
  if (n == null) return '—'
  if (n < 1000) return `${Math.round(n)} ms`
  return `${(n / 1000).toFixed(2)}s`
}

export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n == null ? '—' : `${n.toFixed(digits)}%`

export function relTime(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return `${Math.max(1, Math.floor(s))}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export const shortId = (id: string, n = 8) =>
  id.length <= n + 2 ? id : `${id.slice(0, n)}…${id.slice(-4)}`

export const clockTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour12: false })

/** Render text with <ENTITY> mask tokens highlighted. */
export function maskedParts(text: string): Array<{ token: boolean; text: string }> {
  const parts: Array<{ token: boolean; text: string }> = []
  const re = /<([A-Z_]{3,20})>/g
  let last = 0
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push({ token: false, text: text.slice(last, m.index) })
    parts.push({ token: true, text: m[0] })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ token: false, text: text.slice(last) })
  return parts
}
