import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, KeyRound, LogOut, Shield, User as UserIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { changeMyPassword, type UserRole } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

const ROLE_LABEL: Record<UserRole, string> = {
  admin: '管理员',
  user: '普通用户',
  guest: '访客',
}

export function UserMenu() {
  const { user, isAdmin, isGuest, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [showPwdDialog, setShowPwdDialog] = useState(false)
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdError, setPwdError] = useState('')
  const [pwdLoading, setPwdLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const handleLogout = async () => {
    await logout()
    setOpen(false)
    navigate('/')
  }

  const handleChangePassword = async () => {
    setPwdError('')
    if (!newPwd) {
      setPwdError('请输入新密码')
      return
    }
    if (newPwd.length < 6) {
      setPwdError('新密码至少 6 位')
      return
    }
    if (newPwd !== confirmPwd) {
      setPwdError('两次输入的新密码不一致')
      return
    }
    setPwdLoading(true)
    try {
      await changeMyPassword(oldPwd, newPwd)
      setShowPwdDialog(false)
      setOldPwd('')
      setNewPwd('')
      setConfirmPwd('')
      // 修改密码后会话失效，需要重新登录
      await logout()
      navigate('/login')
    } catch (err) {
      setPwdError(err instanceof Error ? err.message : String(err))
    } finally {
      setPwdLoading(false)
    }
  }

  if (!user) return null

  const roleColor =
    user.role === 'admin'
      ? 'bg-amber-500/15 text-amber-600 border-amber-500/30'
      : user.role === 'user'
        ? 'bg-blue-500/15 text-blue-600 border-blue-500/30'
        : 'bg-gray-500/15 text-gray-600 border-gray-500/30'

  return (
    <>
      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-sm hover:bg-accent transition-colors"
        >
          <div className="w-6 h-6 rounded-full flex items-center justify-center bg-primary/10 text-primary text-xs font-medium">
            {user.username.slice(0, 1).toUpperCase()}
          </div>
          <span className="hidden sm:inline text-foreground">{user.username}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${roleColor}`}>{ROLE_LABEL[user.role]}</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 w-48 bg-background border rounded-lg shadow-lg py-1 z-50">
            <div className="px-3 py-2 border-b">
              <div className="text-sm font-medium truncate">{user.username}</div>
              <div className="text-xs text-muted-foreground">{ROLE_LABEL[user.role]}</div>
            </div>
            {!isGuest && (
              <button
                onClick={() => {
                  setOpen(false)
                  setShowPwdDialog(true)
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left"
              >
                <KeyRound className="h-4 w-4" />
                修改密码
              </button>
            )}
            {isAdmin && (
              <button
                onClick={() => {
                  setOpen(false)
                  navigate('/users')
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left"
              >
                <Shield className="h-4 w-4" />
                用户管理
              </button>
            )}
            {isGuest ? (
              <button
                onClick={() => {
                  setOpen(false)
                  navigate('/login')
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left"
              >
                <UserIcon className="h-4 w-4" />
                登录
              </button>
            ) : (
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left text-destructive"
              >
                <LogOut className="h-4 w-4" />
                注销
              </button>
            )}
          </div>
        )}
      </div>

      <Dialog open={showPwdDialog} onOpenChange={setShowPwdDialog}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>修改密码</DialogTitle>
            <DialogDescription>修改成功后会话将失效，需要重新登录</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              type="password"
              placeholder="原密码"
              value={oldPwd}
              onChange={(e) => setOldPwd(e.target.value)}
              autoComplete="current-password"
            />
            <Input
              type="password"
              placeholder="新密码（至少 6 位）"
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              autoComplete="new-password"
            />
            <Input
              type="password"
              placeholder="再次输入新密码"
              value={confirmPwd}
              onChange={(e) => setConfirmPwd(e.target.value)}
              autoComplete="new-password"
            />
            {pwdError && <p className="text-xs text-destructive">{pwdError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setShowPwdDialog(false)} disabled={pwdLoading}>
                取消
              </Button>
              <Button onClick={handleChangePassword} disabled={pwdLoading}>
                {pwdLoading ? '提交中...' : '确认修改'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
