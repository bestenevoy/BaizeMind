import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Brain, Loader2, Lock, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'

export function LoginPage() {
  const { login, isAuthenticated, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 已登录用户访问 /login 直接回首页
  if (!authLoading && isAuthenticated) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (loading) return
    setError('')
    setLoading(true)
    try {
      await login(username.trim(), password)
      // 登录成功跳转首页
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-muted/30 px-4">
      <Card className="w-full max-w-sm">
        <CardContent className="pt-8 pb-6 px-8">
          <div className="flex flex-col items-center mb-6">
            <div
              className="w-12 h-12 rounded-2xl flex items-center justify-center mb-3"
              style={{ background: 'var(--gradient-brand)' }}
            >
              <Brain className="h-6 w-6 text-white" />
            </div>
            <h1 className="text-xl font-bold text-gradient-brand">Agentic RAG</h1>
            <p className="text-xs text-muted-foreground mt-1">登录以使用完整功能</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="用户名"
                className="pl-9"
                autoFocus
                autoComplete="username"
                disabled={loading}
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="密码"
                className="pl-9"
                autoComplete="current-password"
                disabled={loading}
              />
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}

            <Button type="submit" disabled={loading || !username.trim() || !password} className="w-full" style={{ background: 'var(--gradient-brand)' }}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              登录
            </Button>
          </form>

          <p className="text-xs text-muted-foreground mt-4 text-center">
            访客可直接关闭此页浏览，但无法上传或修改内容
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
