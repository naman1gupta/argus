import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import MyUsage from './pages/MyUsage'
import Projects from './pages/Projects'
import Requests from './pages/Requests'
import Sessions from './pages/Sessions'

function Guard({ admin, children }: { admin?: boolean; children: React.ReactElement }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="fixed inset-0 grid place-items-center" style={{ color: 'var(--muted)' }}>Loading…</div>
  if (!me) return <Navigate to="/login" replace />
  if (admin && me.role !== 'admin') return <Navigate to="/chat" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Guard><Layout /></Guard>}>
        <Route path="/" element={<Guard admin><Dashboard /></Guard>} />
        <Route path="/requests" element={<Guard admin><Requests /></Guard>} />
        <Route path="/requests/:generationId" element={<Guard admin><Requests /></Guard>} />
        <Route path="/sessions" element={<Guard admin><Sessions /></Guard>} />
        <Route path="/projects" element={<Guard admin><Projects /></Guard>} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/usage" element={<MyUsage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
