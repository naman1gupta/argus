import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type ThemeState = { theme: 'dark' | 'light'; toggle: () => void }
const ThemeContext = createContext<ThemeState>(null!)
export const useTheme = () => useContext(ThemeContext)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('argus-theme') as 'dark' | 'light') || 'dark',
  )
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('argus-theme', theme)
  }, [theme])
  return (
    <ThemeContext.Provider
      value={{ theme, toggle: () => setTheme(t => (t === 'dark' ? 'light' : 'dark')) }}
    >
      {children}
    </ThemeContext.Provider>
  )
}
