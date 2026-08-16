import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import { fmtCost, relTime } from '../lib/format'

type Project = {
  id: string; name: string; environment: string; key_hint: string
  key_rotated_at: string; created_at: string
}
type CreatedProject = Project & { ingestion_key: string }
type Budget = { project_id: string; month_spend: number; budget: number | null; exceeded: boolean; warning: boolean }

const QUICKSTART = `pip install argus-sdk

import argus, anthropic
argus.init(endpoint="http://localhost:8000/api/v1",
           api_key="argus_sk_...", session_id=conversation_id)

client = argus.wrap_anthropic(anthropic.Anthropic())
# use the client exactly as before — every call (incl. streaming) is
# logged: provider, model, latency, TTFT, tokens, cost, errors, masked previews`

export default function Projects() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [revealed, setRevealed] = useState<{ name: string; key: string } | null>(null)

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api<Project[]>('/projects') })
  const budgets = useQuery({ queryKey: ['budgets'], queryFn: () => api<Budget[]>('/insights/budgets') })

  const create = useMutation({
    mutationFn: (n: string) => api<CreatedProject>('/projects', { method: 'POST', body: { name: n } }),
    onSuccess: p => {
      setRevealed({ name: p.name, key: p.ingestion_key })
      setName('')
      void qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const rotate = useMutation({
    mutationFn: (id: string) => api<CreatedProject>(`/projects/${id}/rotate-key`, { method: 'POST' }),
    onSuccess: p => {
      setRevealed({ name: p.name, key: p.ingestion_key })
      void qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const setBudget = useMutation({
    mutationFn: ({ id, value }: { id: string; value: number | null }) =>
      api(`/insights/budgets/${id}`, { method: 'PATCH', body: { monthly_budget_usd: value } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['budgets'] }),
  })

  const budgetFor = (id: string) => budgets.data?.find(b => b.project_id === id)

  return (
    <div>
      <h1 className="text-lg font-bold mb-1">Projects & API keys</h1>
      <div className="text-[12.5px] mb-4" style={{ color: 'var(--muted)' }}>
        Telemetry is scoped per project. Each project gets an ingestion key (hashed at rest, shown once). Admin-only.
      </div>

      <div className="flex gap-2 mb-4">
        <input className="input w-[240px]" placeholder="new project name" value={name} onChange={e => setName(e.target.value)} />
        <button className="btn-primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate(name.trim())}>
          ＋ Create project
        </button>
      </div>

      {revealed && (
        <div className="card mb-4" style={{ borderColor: 'var(--s1)' }}>
          <div className="text-[12.5px] mb-1.5">
            Ingestion key for <b>{revealed.name}</b> — copy it now, it will not be shown again:
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            <code className="mono px-2.5 py-1.5 rounded-lg break-all" style={{ background: 'var(--surface2)' }}>{revealed.key}</code>
            <button className="btn-ghost" onClick={() => navigator.clipboard.writeText(revealed.key)}>copy</button>
            <button className="btn-ghost" onClick={() => setRevealed(null)}>dismiss</button>
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-3 mb-4">
        {(projects.data ?? []).map(p => {
          const b = budgetFor(p.id)
          return (
            <div key={p.id} className="card">
              <div className="flex items-center gap-2.5 mb-2.5">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--s3)', boxShadow: '0 0 8px rgba(25,158,112,.7)' }} />
                <b className="text-[14px]">{p.name}</b>
                <span className="chip ml-auto">{p.environment}</span>
              </div>
              <div className="flex items-center gap-2 text-[12px] flex-wrap" style={{ color: 'var(--ink2)' }}>
                Ingestion key <span className="mono px-2 py-1 rounded" style={{ background: 'var(--surface2)' }}>{p.key_hint}</span>
                <button className="btn-ghost !px-2 !py-0.5 !text-[11px]" onClick={() => rotate.mutate(p.id)}>rotate</button>
              </div>
              <div className="flex gap-4 mt-3 text-[11.5px] items-center flex-wrap" style={{ color: 'var(--muted)' }}>
                <span>month spend <b style={{ color: 'var(--ink2)' }}>{fmtCost(b?.month_spend ?? 0)}</b></span>
                <span>
                  budget{' '}
                  <input
                    className="input !py-0.5 !px-1.5 w-[76px] !text-[11.5px] tabular-nums"
                    defaultValue={b?.budget ?? ''}
                    placeholder="none"
                    onBlur={e => {
                      const v = e.target.value.trim()
                      setBudget.mutate({ id: p.id, value: v === '' ? null : Number(v) })
                    }}
                  />
                </span>
                {b?.exceeded && <span className="pill error">budget exceeded</span>}
                {!b?.exceeded && b?.warning && <span className="pill pending">over 80%</span>}
                <span>key rotated {relTime(p.key_rotated_at)}</span>
              </div>
            </div>
          )
        })}
      </div>

      <div className="card">
        <h3 className="text-[12.5px] font-semibold mb-1" style={{ color: 'var(--ink2)' }}>SDK quickstart</h3>
        <div className="text-[11px] mb-2.5" style={{ color: 'var(--muted)' }}>
          zero code changes to your LLM calls — wrap the client once
        </div>
        <pre
          className="rounded-lg border p-3.5 overflow-x-auto text-[11.5px] leading-relaxed m-0"
          style={{ background: 'var(--page)', borderColor: 'var(--border)', color: 'var(--ink2)', fontFamily: 'var(--mono)' }}
        >
          {QUICKSTART}
        </pre>
      </div>
    </div>
  )
}
