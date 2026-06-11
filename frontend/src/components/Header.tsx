import { Brain, Home, Settings, FlaskConical } from 'lucide-react'
import { useEffect, useState } from 'react'
import { healthCheck } from '@/lib/api'

interface HeaderProps {
  page: string
  onNavigate: (page: string) => void
}

export function Header({ page, onNavigate }: HeaderProps) {
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
    { id: 'home', label: '主页', icon: Home },
    { id: 'config', label: '配置', icon: Settings },
    { id: 'tests', label: '测试', icon: FlaskConical },
  ]

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center justify-between">
        <a className="flex items-center space-x-2 cursor-pointer" onClick={() => onNavigate('home')}>
          <Brain className="h-6 w-6 text-primary" />
          <span className="font-bold">Agentic-GraphRAG</span>
        </a>

        <nav className="flex items-center space-x-1">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onNavigate(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                page === id
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-1.5 text-xs">
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
