import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const go = async (u: string, p: string) => {
    setBusy(true)
    setError('')
    try {
      const me = await login(u, p)
      navigate(me.role === 'admin' ? '/' : '/chat')
    } catch {
      setError('Invalid credentials')
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void go(username, password)
  }

  return (
    <div className="fixed inset-0 grid place-items-center overflow-hidden" style={{ background: 'var(--page)' }}>
      <div className="absolute rounded-full blur-[90px] opacity-50 w-[420px] h-[420px] -top-[120px] -left-[80px]" style={{ background: '#1c4f9c' }} />
      <div className="absolute rounded-full blur-[90px] opacity-50 w-[380px] h-[380px] -bottom-[140px] -right-[60px]" style={{ background: '#4d3fa8' }} />
      <div className="absolute rounded-full blur-[90px] opacity-30 w-[220px] h-[220px] bottom-[10%] left-[12%]" style={{ background: '#0f6f4e' }} />
      <form
        onSubmit={submit}
        className="relative w-[400px] max-w-[92vw] rounded-2xl border p-8 pb-6 backdrop-blur-xl"
        style={{ background: 'color-mix(in srgb, var(--surface) 85%, transparent)', borderColor: 'var(--border2)', boxShadow: '0 30px 80px rgba(0,0,0,.55)' }}
      >
        <div className="flex items-center gap-3 mb-1">
          <div className="w-8 h-8 rounded-lg grid place-items-center font-extrabold text-white" style={{ background: 'var(--accent)' }}>A</div>
          <div>
            <b className="text-[17px]">Argus</b>
            <span className="block text-[10.5px]" style={{ color: 'var(--muted)' }}>LLM inference logging</span>
          </div>
        </div>
        <p className="text-[12.5px] mb-6" style={{ color: 'var(--muted)' }}>
          Every inference. Captured, measured, accountable.
        </p>
        <label className="block text-[11px] font-semibold uppercase tracking-[0.6px] mb-1.5" style={{ color: 'var(--muted)' }}>Username</label>
        <input className="input w-full mb-3" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
        <label className="block text-[11px] font-semibold uppercase tracking-[0.6px] mb-1.5" style={{ color: 'var(--muted)' }}>Password</label>
        <input className="input w-full mb-4" type="password" value={password} onChange={e => setPassword(e.target.value)} />
        {error && <div className="text-[12px] mb-3" style={{ color: 'var(--errink)' }}>{error}</div>}
        <button className="btn-primary w-full" disabled={busy} type="submit">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <div className="flex items-center gap-2.5 my-4 text-[11px]" style={{ color: 'var(--muted)' }}>
          <span className="flex-1 h-px" style={{ background: 'var(--border)' }} />or
          <span className="flex-1 h-px" style={{ background: 'var(--border)' }} />
        </div>
        <button type="button" className="btn-ghost w-full opacity-55 cursor-not-allowed" title="Documented as future work">
          Continue with Google <span className="text-[10px] border rounded-full px-1.5 ml-1" style={{ borderColor: 'var(--border)' }}>coming soon</span>
        </button>
        <div className="text-[11px] text-center mt-4" style={{ color: 'var(--muted)' }}>
          Demo credentials are in the README — <b>admin</b> sees everything,
          <b> member</b> gets chat + their own usage (RBAC).
        </div>
      </form>
    </div>
  )
}
