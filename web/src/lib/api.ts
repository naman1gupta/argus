const BASE = '/api/v1'

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return m ? m[1] : ''
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = opts.method ?? 'GET'
  const resp = await fetch(BASE + path, {
    method,
    headers: {
      ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRFToken': csrfToken() } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: 'same-origin',
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch { /* not json */ }
    throw new ApiError(resp.status, detail)
  }
  return resp.json() as Promise<T>
}

export type SseEvent = { event: string; data: unknown }

/** POST that returns an SSE-formatted stream (chat). Yields parsed events. */
export async function* streamSse(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const resp = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify(body),
    credentials: 'same-origin',
    signal,
  })
  if (!resp.ok || !resp.body) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch { /* not json */ }
    throw new ApiError(resp.status, detail)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) yield { event, data: JSON.parse(data) }
    }
  }
}
