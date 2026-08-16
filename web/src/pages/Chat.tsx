import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth'
import { api, streamSse } from '../lib/api'
import { relTime } from '../lib/format'
import { StatusPill } from '../components/ui'

type SessionRow = { id: string; title: string; updated_at: string; message_count: number }
type Msg = { role: string; content: string; provider?: string; model?: string; streaming?: boolean; error?: string; aborted?: boolean }
type Provider = { name: string; label: string; models: string[]; available: boolean; is_default: boolean }
type ProvidersResponse = { providers: Provider[]; default: { provider: string; model: string } }

export default function Chat() {
  const { me } = useAuth()
  const qc = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [pm, setPm] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionRow[]>('/chat/sessions') })
  const providersQuery = useQuery({
    queryKey: ['providers'],
    queryFn: () => api<ProvidersResponse>('/chat/providers'),
  })
  const providers = { data: providersQuery.data?.providers }

  // Default provider/model comes from the server (DEFAULT_PROVIDER / DEFAULT_MODEL),
  // falling back to the keyless mock when that provider has no key configured.
  useEffect(() => {
    const d = providersQuery.data?.default
    if (d && !pm) setPm(`${d.provider}::${d.model}`)
  }, [providersQuery.data, pm])

  const loadSession = async (id: string) => {
    setSessionId(id)
    const rows = await api<Msg[]>(`/chat/sessions/${id}/messages`)
    setMsgs(rows)
  }

  const newSession = useMutation({
    mutationFn: () => api<SessionRow>('/chat/sessions', { method: 'POST' }),
    onSuccess: s => {
      void qc.invalidateQueries({ queryKey: ['sessions'] })
      setSessionId(s.id)
      setMsgs([])
    },
  })

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [msgs])

  const send = async () => {
    const content = input.trim()
    if (!content || streaming) return
    let sid = sessionId
    if (!sid) {
      const s = await api<SessionRow>('/chat/sessions', { method: 'POST' })
      sid = s.id
      setSessionId(sid)
    }
    const [provider, model] = pm.split('::')
    setInput('')
    setMsgs(prev => [...prev, { role: 'user', content }, { role: 'assistant', content: '', provider, model, streaming: true }])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      for await (const ev of streamSse(`/chat/sessions/${sid}/messages`, { content, provider, model }, controller.signal)) {
        if (ev.event === 'token') {
          const d = (ev.data as { d: string }).d
          setMsgs(prev => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + d }
            return next
          })
        } else if (ev.event === 'error') {
          const detail = (ev.data as { detail: string }).detail
          setMsgs(prev => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], streaming: false, error: detail }
            return next
          })
        } else if (ev.event === 'done') {
          setMsgs(prev => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], streaming: false }
            return next
          })
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        setMsgs(prev => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], streaming: false, aborted: true }
          return next
        })
      } else {
        setMsgs(prev => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], streaming: false, error: (err as Error).message }
          return next
        })
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      void qc.invalidateQueries({ queryKey: ['sessions'] })
    }
  }

  const cancel = () => abortRef.current?.abort()

  return (
    <div className="h-full flex flex-col">
      <h1 className="text-lg font-bold mb-1">Chat</h1>
      <div className="text-[12.5px] mb-3.5" style={{ color: 'var(--muted)' }}>
        Multi-turn conversations with any configured provider. Cancel mid-stream, resume any time.
        {me?.role === 'admin' && ' Every message lands in Requests → LIVE.'}
      </div>
      <div className="flex-1 min-h-0 grid md:grid-cols-[270px_1fr] gap-3.5">
        <div className="card !p-2.5 overflow-y-auto hidden md:flex flex-col">
          <button className="btn-primary w-full mb-2.5 !py-2" onClick={() => newSession.mutate()}>
            ＋ New conversation
          </button>
          {(sessions.data ?? []).map(s => (
            <button
              key={s.id}
              onClick={() => void loadSession(s.id)}
              className="text-left px-2.5 py-2 rounded-lg mb-0.5 border-0 cursor-pointer text-[12.5px]"
              style={{
                background: s.id === sessionId ? 'var(--surface3)' : 'transparent',
                color: s.id === sessionId ? 'var(--ink)' : 'var(--ink2)',
                boxShadow: s.id === sessionId ? 'inset 3px 0 0 var(--s1)' : undefined,
              }}
            >
              <div className="truncate">{s.title || 'untitled conversation'}</div>
              <div className="flex gap-2 text-[10.5px] mt-0.5" style={{ color: 'var(--muted)' }}>
                <span>{s.message_count} msgs</span>
                <span>{relTime(s.updated_at)}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="card !p-0 flex flex-col min-h-0">
          <div className="flex gap-2.5 items-center px-4 py-2.5 border-b flex-wrap" style={{ borderColor: 'var(--border)' }}>
            <select className="input font-semibold" value={pm} onChange={e => setPm(e.target.value)}>
              {(providers.data ?? []).flatMap(p =>
                p.models.map(m => (
                  <option key={`${p.name}::${m}`} value={`${p.name}::${m}`} disabled={!p.available}>
                    {p.label} · {m} {p.available ? '' : '(no key)'}
                  </option>
                )),
              )}
            </select>
            <span className="chip">streaming <b>on</b></span>
            {sessionId && <span className="chip ml-auto hidden sm:inline mono">session {sessionId.slice(0, 10)}…</span>}
          </div>
          {pm.startsWith('mock') && (
            <div
              className="px-4 py-2 text-[11.5px] border-b"
              style={{ color: 'var(--muted)', borderColor: 'var(--border)', background: 'var(--surface2)' }}
            >
              Mock provider echoes your message instead of answering it — it exists so every
              feature is demoable with zero API keys.{' '}
              {(providers.data ?? []).some(p => p.available && p.name !== 'mock')
                ? 'Pick a configured provider above for real model responses.'
                : 'Add GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY to .env for real model responses.'}
            </div>
          )}

          <div ref={bodyRef} className="flex-1 overflow-y-auto p-4">
            {msgs.length === 0 && (
              <div className="h-full grid place-items-center text-center text-[13px]" style={{ color: 'var(--muted)' }}>
                <div>
                  Start a conversation — try the <b>mock</b> provider with zero API keys.
                  <br />
                  <span className="text-[11.5px]">Tip: include “trigger error” in a message to demo the error path.</span>
                </div>
              </div>
            )}
            {msgs.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="bubble u-msg mb-3.5">{m.content}</div>
              ) : (
                <div key={i} className="mb-3.5">
                  <div className="bubble a-msg">
                    {m.content}
                    {m.streaming && <span className="cursor-blink ml-0.5" />}
                    {m.error && <div className="mt-1 text-[12px]" style={{ color: 'var(--errink)' }}>⚠ {m.error}</div>}
                  </div>
                  <div className="flex gap-1.5 mt-1 flex-wrap text-[10.5px]" style={{ color: 'var(--muted)' }}>
                    {m.streaming && <StatusPill status="pending" />}
                    {m.aborted && <StatusPill status="aborted" />}
                    {m.error && <StatusPill status="error" />}
                    {m.model && <span className="chip !py-0.5">{m.model}</span>}
                    {m.aborted && <span className="chip !py-0.5">partial · usage estimated</span>}
                  </div>
                </div>
              ),
            )}
          </div>

          <div className="flex gap-2.5 px-4 py-3.5 border-t" style={{ borderColor: 'var(--border)' }}>
            <input
              className="input flex-1"
              placeholder="Message… (⏎ to send)"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && void send()}
            />
            {streaming ? (
              <button
                className="btn-ghost !font-bold"
                style={{ color: 'var(--serious)', borderColor: 'rgba(236,131,90,.5)' }}
                onClick={cancel}
              >
                ◼ Stop
              </button>
            ) : (
              <button className="btn-primary" onClick={() => void send()} disabled={!input.trim()}>
                Send
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
