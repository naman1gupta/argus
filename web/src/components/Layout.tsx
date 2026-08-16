import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { useTheme } from '../theme'

const NAV = [
  { to: '/', label: 'Dashboard', admin: true, icon: 'M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-4H3zM13 7h8V3h-8z', group: 'Observe' },
  { to: '/requests', label: 'Requests', admin: true, icon: 'M4 6h16M4 12h16M4 18h10', group: 'Observe' },
  { to: '/sessions', label: 'Sessions', admin: true, icon: 'M21 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0zM8 10h8M8 14h5', group: 'Observe' },
  { to: '/chat', label: 'Chat', admin: false, icon: 'M21 12c0 4-4 7-9 7-1.2 0-2.4-.2-3.4-.5L3 20l1.6-4C3.6 14.9 3 13.5 3 12c0-4 4-7 9-7s9 3 9 7z', group: 'Use' },
  { to: '/usage', label: 'My usage', admin: false, icon: 'M12 3v18M5 12l7-7 7 7', group: 'Use' },
  { to: '/projects', label: 'Projects & keys', admin: true, icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 1-.1 1.2l2 1.6-2 3.4-2.4-1a7 7 0 0 1-2 1.2L14 21h-4l-.4-2.6a7 7 0 0 1-2-1.2l-2.5 1-2-3.4 2-1.6A7 7 0 0 1 5 12', group: 'Configure' },
]

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2.5 pb-4 pt-1">
      <div
        className="w-7 h-7 rounded-lg grid place-items-center font-extrabold text-sm text-white"
        style={{ background: 'var(--accent)', boxShadow: '0 4px 14px rgba(87,109,227,.45)' }}
      >
        A
      </div>
      <div>
        <b className="text-[15.5px]">Argus</b>
        <span className="block text-[10px] -mt-0.5" style={{ color: 'var(--muted)' }}>
          LLM inference logging
        </span>
      </div>
    </div>
  )
}

export default function Layout() {
  const { me, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const isAdmin = me?.role === 'admin'
  const items = NAV.filter(n => isAdmin || !n.admin)
  const groups = [...new Set(items.map(i => i.group))]

  const nav = (
    <nav className="flex flex-col h-full p-2.5" style={{ background: 'var(--surface)' }}>
      <Logo />
      {groups.map(g => (
        <div key={g}>
          <div className="text-[10px] uppercase tracking-[0.8px] font-bold px-2.5 pt-3 pb-1.5" style={{ color: 'var(--muted)' }}>
            {g}
          </div>
          {items.filter(i => i.group === g).map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={() => setMenuOpen(false)}
              className="relative flex items-center gap-2.5 px-2.5 py-2 rounded-lg mb-0.5 font-medium text-[13.5px] no-underline"
              style={({ isActive }) => ({
                color: isActive ? 'var(--ink)' : 'var(--ink2)',
                background: isActive
                  ? 'linear-gradient(90deg,rgba(57,135,229,.16),rgba(144,133,233,.07))'
                  : undefined,
                boxShadow: isActive ? 'inset 3px 0 0 var(--s1)' : undefined,
              })}
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.7">
                <path d={item.icon} />
              </svg>
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-auto px-2.5 py-3 text-[11px] leading-relaxed border-t" style={{ color: 'var(--muted)', borderColor: 'var(--border)' }}>
        API <span style={{ color: 'var(--good)' }}>●</span> healthy · argus-sdk v0.1.0
        <br />
        <a href="/api/v1/docs" target="_blank" rel="noreferrer" className="underline" style={{ color: 'var(--muted)' }}>
          API docs ↗
        </a>
      </div>
    </nav>
  )

  return (
    <div className="flex h-screen relative z-[1]">
      <aside className="w-[212px] shrink-0 border-r hidden md:block" style={{ borderColor: 'var(--border)' }}>
        {nav}
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setMenuOpen(false)}>
          <div className="absolute inset-0" style={{ background: 'rgba(0,0,0,.5)' }} />
          <aside className="absolute left-0 top-0 bottom-0 w-[240px]" onClick={e => e.stopPropagation()}>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <header
          className="h-[54px] shrink-0 flex items-center gap-3 px-4 border-b relative"
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
        >
          <button className="md:hidden btn-ghost !px-2.5" onClick={() => setMenuOpen(true)} aria-label="menu">
            ☰
          </button>
          <div
            className="hidden sm:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-semibold"
            style={{ background: 'var(--surface2)', borderColor: 'var(--border)' }}
          >
            <span className="w-2 h-2 rounded-full" style={{ background: 'var(--s3)', boxShadow: '0 0 8px rgba(25,158,112,.8)' }} />
            default
            <span className="text-[10px] font-medium rounded-full border px-1.5" style={{ color: 'var(--muted)', borderColor: 'var(--border)' }}>
              production
            </span>
          </div>
          <div className="flex-1" />
          <button className="btn-ghost" onClick={toggle} title="toggle theme">
            {theme === 'dark' ? '☀︎ Light' : '☾ Dark'}
          </button>
          <button
            className="flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-[12px] cursor-pointer"
            style={{ background: 'var(--surface2)', borderColor: 'var(--border)', color: 'var(--ink2)' }}
            onClick={async () => {
              await logout()
              navigate('/login')
            }}
            title="sign out"
          >
            <span
              className="w-6 h-6 rounded-full grid place-items-center text-[11px] font-bold text-white"
              style={{ background: 'var(--accent)' }}
            >
              {me?.username[0]?.toUpperCase()}
            </span>
            <span className="hidden sm:inline">{me?.username}</span>
            <span style={{ color: 'var(--muted)' }}>{me?.role} · sign out</span>
          </button>
          <span
            className="absolute left-0 right-0 -bottom-px h-px"
            style={{ background: 'linear-gradient(90deg,transparent,rgba(87,120,230,.5),transparent)' }}
          />
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-5 view-enter">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
