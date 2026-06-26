import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plus, RotateCw, Trash2, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  adminCreateUser,
  adminDeleteUser,
  adminListUsers,
  adminResetUserPassword,
  adminUpdateUserRole,
  type AdminUser,
  type UserRole,
} from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

const ROLE_LABEL: Record<UserRole, string> = {
  admin: '管理员',
  user: '普通用户',
  guest: '访客',
}

export function UsersPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 创建用户对话框
  const [showCreate, setShowCreate] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<UserRole>('user')
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState('')

  // 重置密码对话框
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null)
  const [resetPwd, setResetPwd] = useState('')
  const [resetLoading, setResetLoading] = useState(false)
  const [resetError, setResetError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const list = await adminListUsers()
      setUsers(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async () => {
    setCreateError('')
    if (!newUsername.trim()) {
      setCreateError('请输入用户名')
      return
    }
    if (newPassword.length < 6) {
      setCreateError('密码至少 6 位')
      return
    }
    setCreateLoading(true)
    try {
      await adminCreateUser(newUsername.trim(), newPassword, newRole)
      setShowCreate(false)
      setNewUsername('')
      setNewPassword('')
      setNewRole('user')
      await load()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreateLoading(false)
    }
  }

  const handleRoleChange = async (u: AdminUser, role: UserRole) => {
    try {
      await adminUpdateUserRole(u.user_id, role)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const handleDelete = async (u: AdminUser) => {
    if (u.user_id === currentUser?.user_id) {
      setError('不能删除当前登录的管理员账户')
      return
    }
    if (!confirm(`确认删除用户 ${u.username}？`)) return
    try {
      await adminDeleteUser(u.user_id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const handleResetPassword = async () => {
    if (!resetTarget) return
    setResetError('')
    if (resetPwd.length < 6) {
      setResetError('新密码至少 6 位')
      return
    }
    setResetLoading(true)
    try {
      await adminResetUserPassword(resetTarget.user_id, resetPwd)
      setResetTarget(null)
      setResetPwd('')
    } catch (err) {
      setResetError(err instanceof Error ? err.message : String(err))
    } finally {
      setResetLoading(false)
    }
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold">用户管理</h1>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              <RotateCw className="h-4 w-4 mr-1" />
              刷新
            </Button>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="h-4 w-4 mr-1" />
              新建用户
            </Button>
          </div>
        </div>

        {error && <p className="text-sm text-destructive mb-3">{error}</p>}

        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">用户名</th>
                  <th className="text-left px-3 py-2 font-medium">角色</th>
                  <th className="text-left px-3 py-2 font-medium">状态</th>
                  <th className="text-left px-3 py-2 font-medium">创建时间</th>
                  <th className="text-right px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id} className="border-t hover:bg-muted/30">
                    <td className="px-3 py-2 font-medium">{u.username}</td>
                    <td className="px-3 py-2">
                      <select
                        value={u.role}
                        onChange={(e) => handleRoleChange(u, e.target.value as UserRole)}
                        className="border rounded px-1.5 py-0.5 bg-background text-xs"
                        disabled={u.user_id === currentUser?.user_id}
                      >
                        <option value="admin">{ROLE_LABEL.admin}</option>
                        <option value="user">{ROLE_LABEL.user}</option>
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${u.active ? 'bg-green-500/15 text-green-600' : 'bg-red-500/15 text-red-600'}`}>
                        {u.active ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground text-xs">
                      {u.created_at?.slice(0, 19).replace('T', ' ') || '-'}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setResetTarget(u)
                          setResetPwd('')
                          setResetError('')
                        }}
                      >
                        重置密码
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        onClick={() => handleDelete(u)}
                        disabled={u.user_id === currentUser?.user_id}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 创建用户对话框 */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>新建用户</DialogTitle>
            <DialogDescription>普通用户可以上传内容，受每日上传配额限制</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="用户名"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              autoComplete="off"
            />
            <Input
              type="password"
              placeholder="密码（至少 6 位）"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">角色</label>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as UserRole)}
                className="w-full border rounded px-2 py-1.5 bg-background text-sm"
              >
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </div>
            {createError && <p className="text-xs text-destructive">{createError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createLoading}>
                取消
              </Button>
              <Button onClick={handleCreate} disabled={createLoading}>
                {createLoading ? '创建中...' : '创建'}
                <UserPlus className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 重置密码对话框 */}
      <Dialog
        open={!!resetTarget}
        onOpenChange={(open) => {
          if (!open) setResetTarget(null)
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>重置密码</DialogTitle>
            <DialogDescription>为用户 {resetTarget?.username} 设置新密码</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              type="password"
              placeholder="新密码（至少 6 位）"
              value={resetPwd}
              onChange={(e) => setResetPwd(e.target.value)}
              autoFocus
            />
            {resetError && <p className="text-xs text-destructive">{resetError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setResetTarget(null)} disabled={resetLoading}>
                取消
              </Button>
              <Button onClick={handleResetPassword} disabled={resetLoading}>
                {resetLoading ? '提交中...' : '确认重置'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
