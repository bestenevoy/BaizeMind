import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  type UserInfo,
  type UserRole,
} from '@/lib/api'

interface AuthContextValue {
  user: UserInfo | null
  loading: boolean  // 初始加载中
  /** 简化的角色快捷判断 */
  isAdmin: boolean
  isUser: boolean
  isGuest: boolean
  /** 是否已登录（非访客） */
  isAuthenticated: boolean
  /** 是否有上传权限（admin / user） */
  canUpload: boolean
  /** 是否可以执行修改/删除等管理操作（仅 admin） */
  canManage: boolean
  login: (username: string, password: string) => Promise<UserInfo>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

const GUEST_USER: UserInfo = {
  user_id: '',
  username: 'guest',
  role: 'guest',
  is_guest: true,
  upload_used_today: 0,
  upload_limit: 0,
  guest_chat_max_length: 200,
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const u = await getCurrentUser()
    setUser(u)
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await refresh()
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    await apiLogin(username, password)
    const u = await getCurrentUser()
    setUser(u)
    return u
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    setUser({ ...GUEST_USER })
  }, [])

  const value = useMemo<AuthContextValue>(() => {
    const role: UserRole = user?.role ?? 'guest'
    const isGuest = role === 'guest'
    const isUser = role === 'user'
    const isAdmin = role === 'admin'
    return {
      user: user ?? GUEST_USER,
      loading,
      isAdmin,
      isUser,
      isGuest,
      isAuthenticated: !isGuest,
      canUpload: isAdmin || isUser,
      canManage: isAdmin,
      login,
      logout,
      refresh,
    }
  }, [user, loading, login, logout, refresh])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
