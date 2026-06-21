import { useEffect, useState, useCallback } from 'react'
import { getConfig, checkConnectivity, getSystemStats, listEditableConfig, updateConfigOverride, resetConfigOverride, cleanupOrphans } from '@/lib/api'
import type { ConfigResponse, ConnectivityResult, SystemStats, EditableConfigItem } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { RefreshCw, CheckCircle2, AlertTriangle, XCircle, Loader2, Wifi, Save, RotateCcw, Pencil, Trash2 } from 'lucide-react'

function StatusIcon({ status }: { status: string }) {
  if (status === 'ok')
    return <CheckCircle2 className="h-4 w-4 text-green-500" />
  if (status === 'warning')
    return <AlertTriangle className="h-4 w-4 text-yellow-500" />
  return <XCircle className="h-4 w-4 text-red-500" />
}

export function ConfigPage() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [connResults, setConnResults] = useState<ConnectivityResult[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [editableItems, setEditableItems] = useState<EditableConfigItem[]>([])
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const [cfg, st, ed] = await Promise.all([getConfig(), getSystemStats(), listEditableConfig().catch(() => [])])
      setConfig(cfg)
      setStats(st)
      setEditableItems(Array.isArray(ed) ? ed : [])
    } catch {
      setConfig(null)
    }
    setLoading(false)
  }, [])

  const runConnectivityCheck = useCallback(async () => {
    setChecking(true)
    try {
      const results = await checkConnectivity()
      setConnResults(results)
    } catch {
      setConnResults(null)
    }
    setChecking(false)
  }, [])

  const handleSaveOverride = async () => {
    if (!editingKey) return
    setSaving(true)
    try {
      await updateConfigOverride(editingKey, editValue)
      setEditableItems((prev) =>
        prev.map((it) => (it.key === editingKey ? { ...it, value: editValue, overridden: true } : it))
      )
      setEditingKey(null)
    } catch {}
    setSaving(false)
  }

  const handleResetOverride = async (key: string) => {
    try {
      await resetConfigOverride(key)
      loadEditableConfig()
    } catch {}
  }

  const startEdit = (item: EditableConfigItem) => {
    setEditingKey(item.key)
    setEditValue(item.value)
  }

  const loadEditableConfig = async () => {
    try {
      const ed = await listEditableConfig()
      setEditableItems(Array.isArray(ed) ? ed : [])
    } catch {}
  }

  const friendlyValue = (item: EditableConfigItem) => {
    if (item.key === 'reranker_method') {
      const m: Record<string, string> = {
        embedding: 'Cross-Encoder (bge-reranker-v2-m3)',
        llm: 'LLM 排序',
        hybrid: '混合 (Cross-Encoder + LLM)',
      }
      return m[item.value] || item.value
    }
    return item.value
  }

  useEffect(() => {
    loadConfig()
    runConnectivityCheck()
  }, [loadConfig, runConnectivityCheck])

  return (
    <div className="container mx-auto py-6 px-4 max-w-4xl">
      <div className="space-y-6">

        {/* Connectivity Check */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Wifi className="h-5 w-5" />
              连通性检测
            </CardTitle>
            <Button variant="outline" size="sm" onClick={runConnectivityCheck} disabled={checking}>
              {checking ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
              {checking ? '检测中...' : '重新检测'}
            </Button>
          </CardHeader>
          <CardContent>
            {connResults === null ? (
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {connResults.map((r) => (
                  <div
                    key={r.service}
                    className="flex items-center justify-between p-2 rounded-lg border bg-card"
                  >
                    <div className="flex items-center gap-2">
                      <StatusIcon status={r.status} />
                      <div>
                        <p className="text-sm font-medium">{r.service}</p>
                        <p className="text-xs text-muted-foreground">{r.detail}</p>
                      </div>
                    </div>
                    <Badge
                      variant="secondary"
                      className="text-xs shrink-0"
                    >
                      {r.latency_ms > 0 ? `${r.latency_ms}ms` : '-'}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* System Stats Summary */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">系统状态概览</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
              </div>
            ) : stats ? (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold">{stats.document_count}</p>
                  <p className="text-xs text-muted-foreground">文档数</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold">{stats.chunk_count}</p>
                  <p className="text-xs text-muted-foreground">分块数</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold">{stats.milvus_vector_count}</p>
                  <p className="text-xs text-muted-foreground">向量数</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold">{stats.neo4j_entity_count}</p>
                  <p className="text-xs text-muted-foreground">实体数</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold">{stats.neo4j_relation_count}</p>
                  <p className="text-xs text-muted-foreground">关系数</p>
                </div>
              </div>
            ) : null}
            <div className="flex justify-end mt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  if (!confirm('清理 Milvus 和 Neo4j 中不属于任何文档的孤立数据？')) return
                  try {
                    const r = await cleanupOrphans()
                    const parts = [`Milvus: ${r.milvus_deleted}`, `Neo4j: ${r.neo4j_deleted_entities}`]
                    if ((r as any).milvus_error) parts.push(`(Milvus: ${(r as any).milvus_error})`)
                    if ((r as any).neo4j_error) parts.push(`(Neo4j: ${(r as any).neo4j_error})`)
                    alert(`清除完成: ${parts.join(', ')}`)
                    loadConfig()
                  } catch (e: any) { alert(`清理失败: ${e?.message || e}`) }
                }}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                清理孤立数据
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Configuration */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-lg">配置信息</CardTitle>
            <Button variant="outline" size="sm" onClick={loadConfig} disabled={loading}>
              <RefreshCw className="h-4 w-4 mr-1" />
              刷新
            </Button>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full" />)}
              </div>
            ) : config ? (
              <div className="space-y-4">
                {/* API Keys (masked) */}
                <div>
                  <h4 className="text-sm font-medium mb-2">API 密钥 (已脱敏)</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div className="flex justify-between items-center p-2 rounded border text-sm">
                      <span className="text-muted-foreground">DeepSeek API Key</span>
                      <code className="text-xs">{config.secrets.deepseek_api_key || '未配置'}</code>
                    </div>
                    <div className="flex justify-between items-center p-2 rounded border text-sm">
                      <span className="text-muted-foreground">SiliconFlow API Key</span>
                      <code className="text-xs">{config.secrets.siliconflow_api_key || '未配置'}</code>
                    </div>
                  </div>
                </div>

                <Separator />

                {/* Settings categories */}
                {config.categories.map((cat) => (
                  <div key={cat.category}>
                    <h4 className="text-sm font-medium mb-2">{cat.category}</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                      {cat.items.map((item) => (
                        <div
                          key={item.key}
                          className="flex justify-between items-center p-1.5 rounded text-sm hover:bg-muted/50"
                        >
                          <span className="text-muted-foreground">{item.label}</span>
                          <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                            {item.value === 'True' ? '是' : item.value === 'False' ? '否' : item.value || '-'}
                          </code>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">无法加载配置信息</p>
            )}
          </CardContent>
        </Card>

        {/* Editable Runtime Config */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Pencil className="h-5 w-5" />
              运行时配置 (可编辑)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {editableItems.map((item) => (
                <div
                  key={item.key}
                  className="flex items-center gap-3 p-2 rounded border hover:bg-muted/30 text-sm"
                >
                  <span className="w-48 shrink-0 text-muted-foreground font-mono text-xs">
                    {item.key}
                  </span>
                  {editingKey === item.key ? (
                    item.key === 'reranker_method' ? (
                      <div className="flex items-center gap-2 flex-1">
                        <select
                          className="flex-1 h-8 text-xs rounded-md border bg-background px-2"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          autoFocus
                        >
                          <option value="embedding">硅基流动 Cross-Encoder (BAAI/bge-reranker-v2-m3)</option>
                          <option value="llm">LLM 排序</option>
                          <option value="hybrid">混合 (Cross-Encoder + LLM)</option>
                        </select>
                        <Button size="sm" onClick={handleSaveOverride} disabled={saving}>
                          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>
                          取消
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 flex-1">
                        <Input
                          className="flex-1 h-8 text-xs"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleSaveOverride() }}
                          autoFocus
                        />
                        <Button size="sm" onClick={handleSaveOverride} disabled={saving}>
                          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>
                          取消
                        </Button>
                      </div>
                    )
                  ) : (
                    <div className="flex items-center gap-2 flex-1">
                      <code className="text-xs bg-muted px-1.5 py-0.5 rounded min-w-[80px] text-center">
                        {friendlyValue(item) || '-'}
                      </code>
                      {item.overridden && (
                        <Badge variant="secondary" className="text-[10px]">已修改</Badge>
                      )}
                      <div className="ml-auto flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => startEdit(item)} title="编辑">
                          <Pencil className="h-3 w-3" />
                        </Button>
                        {item.overridden && (
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => handleResetOverride(item.key)} title="恢复默认">
                            <RotateCcw className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
