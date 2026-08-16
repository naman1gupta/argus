import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './lib/api'

export type Me = { username: string; role: 'admin' | 'member' }

type AuthState = {
  me: Me | null
  loading: boolean
  login: (username: string, password: string) => Promise<Me>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState>(null!)
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api<Me>('/auth/me')
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false))
  }, [])

  const login = async (username: string, password: string) => {
    const user = await api<Me>('/auth/login', { method: 'POST', body: { username, password } })
    await api<Me>('/auth/me') // refreshes the CSRF cookie post-rotation
    setMe(user)
    return user
  }

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    setMe(null)
  }

  return (
    <AuthContext.Provider value={{ me, loading, login, logout }}>{children}</AuthContext.Provider>
  )
}
