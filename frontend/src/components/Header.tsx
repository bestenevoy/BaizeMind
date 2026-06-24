import { Brain, Home, FileText, Settings, FlaskConical, BarChart3, Network } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { healthCheck } from '@/lib/api'

export function Header() {
  const [online, setOnline] = useState<boolean | null>(null)

  useEffect(() => {
    const check = async () => {
      const ok = await healthCheck()
      setOnline(ok)
    }
    check()
    const interval = setInterval(check, 10000)
    return () => clearInterval(interval)
  }, [])

  const navItems = [
    { to: '/', label: '主页', icon: Home },
    { to: '/documents', label: '文档', icon: FileText },
    { to: '/graph', label: '图谱', icon: Network },
    { to: '/evaluation', label: '评估', icon: BarChart3 },
    { to: '/config', label: '配置', icon: Settings },
    { to: '/tests', label: '测试', icon: FlaskConical },
  ]

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
      isActive
        ? 'bg-primary/10 text-primary font-medium'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent'
    }`

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <nav className="flex items-center space-x-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={linkClass}>
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 text-xs">
          <span
            className={`h-2 w-2 rounded-full ${
              online === null ? 'bg-gray-400 animate-pulse' : online ? 'bg-green-500' : 'bg-red-500'
            }`}
          />
          <span className="text-muted-foreground">
            {online === null ? '...' : online ? '在线' : '离线'}
          </span>
        </div>
      </div>
    </header>
  )
}
