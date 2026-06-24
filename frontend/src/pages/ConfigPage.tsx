import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getConfig, checkConnectivity, getSystemStats, listEditableConfig, updateConfigOverride, resetConfigOverride, cleanupOrphans, buildGraph, buildGraphStatus, deleteAllVectors, deleteAllGraph, deleteInactiveGraph, rebuildBM25 } from '@/lib/api'
import type { ConfigResponse, ConnectivityResult, SystemStats, EditableConfigItem } from '@/lib/api'
import { CONFIG_SCHEMA, validateConfigValue } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { RefreshCw, CheckCircle2, AlertTriangle, XCircle, Loader2, Wifi, Save, RotateCcw, Pencil, Trash2, GitGraph, Settings, Activity } from 'lucide-react'

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
  const [editError, setEditError] = useState('')
  const [saving, setSaving] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildPhase, setRebuildPhase] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') || 'status'
  const setActiveTab = (tab: string) => setSearchParams({ tab })

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
    const err = validateConfigValue(editingKey, editValue)
    if (err) { setEditError(err); return }
    setSaving(true)
    setEditError('')
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
    setEditError('')
  }

  const loadEditableConfig = async () => {
    try {
      const ed = await listEditableConfig()
      setEditableItems(Array.isArray(ed) ? ed : [])
    } catch {}
  }

  const friendlyValue = (item: EditableConfigItem) => {
    const schema = CONFIG_SCHEMA[item.key]
    if (schema?.type === 'bool') return item.value.toLowerCase() === 'true' ? '开启' : '关闭'
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
  }, [loadConfig])

  return (
    <div className="container mx-auto pt-4 px-4 flex flex-col min-h-0 flex-1 max-w-4xl">
      <div className="flex items-end gap-3 flex-none pb-3 border-b mb-4">
        <button
          onClick={() => setActiveTab('status')}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md border border-b-0 transition-colors ${
            activeTab === 'status'
              ? 'bg-background text-foreground border-border font-medium'
              : 'text-muted-foreground hover:text-foreground border-transparent'
          }`}
        >
          <Activity className="h-4 w-4" />
          系统状态
        </button>
        <button
          onClick={() => setActiveTab('info')}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md border border-b-0 transition-colors ${
            activeTab === 'info'
              ? 'bg-background text-foreground border-border font-medium'
              : 'text-muted-foreground hover:text-foreground border-transparent'
          }`}
        >
          <Settings className="h-4 w-4" />
          配置信息
        </button>
        <button
          onClick={() => setActiveTab('runtime')}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md border border-b-0 transition-colors ${
            activeTab === 'runtime'
              ? 'bg-background text-foreground border-border font-medium'
              : 'text-muted-foreground hover:text-foreground border-transparent'
          }`}
        >
          <Pencil className="h-4 w-4" />
          运行时配置
        </button>
        <div className="flex-1 border-b" />
      </div>
      {activeTab === 'status' ? (
      <div className="flex-1 min-h-0 overflow-y-auto space-y-6">

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
              <p className="text-xs text-muted-foreground py-4 text-center">点击右上角"重新检测"开始连通性测试</p>
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
            <div className="flex justify-end gap-2 mt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  if (!confirm('重建知识图谱会重新抽取所有文档的实体和关系，可能需要几分钟。确定？')) return
                  try {
                    setRebuilding(true)
                    setRebuildPhase('启动中...')
                    const start = await buildGraph()
                    if (!start.success) {
                      alert(`启动失败: ${start.message}`)
                      setRebuilding(false)
                      return
                    }
                    const startTime = Date.now()
                    const poll = setInterval(async () => {
                      try {
                        const s = await buildGraphStatus()
                        if (s.done) {
                          clearInterval(poll)
                          setRebuilding(false)
                          const r = s.result
                          if (r?.success) {
                            alert(`图谱重建完成:\n处理 chunk: ${r.chunks_processed}\n证据: ${r.evidence_count}\n同步: ${r.sync_success} 成功${r.sync_failed ? `, ${r.sync_failed} 失败` : ''}${r.errors ? `\n错误: ${r.errors}` : ''}`)
                          } else {
                            alert(`图谱重建失败: ${(r as any)?.message || 'unknown'}`)
                          }
                          loadConfig()
                        } else if (s.running) {
                          const pct = s.total > 0 ? Math.round(s.progress / s.total * 100) : 0
                          setRebuildPhase(s.phase || `${pct}%`)
                          document.title = `[${pct}%] 重建图谱...`
                        }
                        if (Date.now() - startTime > 300000) {
                          clearInterval(poll)
                          setRebuilding(false)
                          alert('重建图谱超时（5分钟），请检查服务状态后重试')
                          loadConfig()
                        }
                      } catch {}
                    }, 2000)
                  } catch (e: any) {
                    alert(`重建图谱失败: ${e?.message || e}`)
                    setRebuilding(false)
                  }
                }}
                disabled={rebuilding}
              >
                <GitGraph className="h-3.5 w-3.5 mr-1" />
                {rebuilding ? (rebuildPhase || '重建中...') : '重建知识图谱'}
              </Button>
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
              <Separator orientation="vertical" className="h-8" />
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  if (!confirm('删除 Neo4j 中所有 active=false 的残留节点？')) return
                  try {
                    const r = await deleteInactiveGraph()
                    alert(`清除完成:\n实体: ${r.entities_deleted}\n事实: ${r.facts_deleted}\n属性: ${r.attrs_deleted}`)
                    loadConfig()
                  } catch (e: any) { alert(`清除失败: ${e?.message || e}`) }
                }}
                className="text-orange-600 border-orange-300 hover:bg-orange-50 dark:hover:bg-orange-950"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                清空不活跃图谱
              </Button>
              <Separator orientation="vertical" className="h-8" />
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  if (!confirm('⚠️ 删除 Milvus 中所有向量数据？此操作不可撤销！')) return
                  if (!confirm('再次确认: 删除所有向量？')) return
                  try {
                    const r = await deleteAllVectors()
                    alert(r.success ? '向量已全部删除' : `删除失败: ${r.message}`)
                    loadConfig()
                  } catch (e: any) { alert(`删除失败: ${e?.message || e}`) }
                }}
                className="text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                清空向量库
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    const r = await rebuildBM25()
                    alert(r.message)
                    loadConfig()
                  } catch (e: any) { alert(`重建失败: ${e?.message || e}`) }
                }}
              >
                <RefreshCw className="h-3.5 w-3.5 mr-1" />
                重建BM25索引
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  if (!confirm('⚠️ 删除 Neo4j 中所有节点和关系？此操作不可撤销！')) return
                  if (!confirm('再次确认: 删除所有图谱数据？')) return
                  try {
                    const r = await deleteAllGraph()
                    alert(r.success ? '图谱已全部删除' : `删除失败: ${r.message}`)
                    loadConfig()
                  } catch (e: any) { alert(`删除失败: ${e?.message || e}`) }
                }}
                className="text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                清空图谱库
              </Button>
            </div>
          </CardContent>
        </Card>

      </div>
      ) : activeTab === 'info' ? (
      <div className="flex-1 min-h-0 overflow-y-auto space-y-6">

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
      </div>
      ) : (
      <div className="flex-1 min-h-0 overflow-y-auto space-y-6">

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
              {editableItems.map((item) => {
                const schema = CONFIG_SCHEMA[item.key]
                const label = schema?.label || item.key
                const isEditing = editingKey === item.key

                return (
                <div
                  key={item.key}
                  className="flex items-center gap-3 p-2 rounded border hover:bg-muted/30 text-sm"
                >
                  <span className="w-48 shrink-0 text-muted-foreground font-mono text-xs">
                    {label}
                  </span>
                  {isEditing ? (
                    <>
                      {schema?.type === 'bool' ? (
                        <div className="flex items-center gap-2 flex-1">
                          <Button
                            size="sm"
                            variant={editValue.toLowerCase() === 'true' ? 'default' : 'outline'}
                            onClick={() => setEditValue('true')}
                          >开启</Button>
                          <Button
                            size="sm"
                            variant={editValue.toLowerCase() === 'false' ? 'default' : 'outline'}
                            onClick={() => setEditValue('false')}
                          >关闭</Button>
                          <Button size="sm" onClick={handleSaveOverride} disabled={saving}>
                            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>取消</Button>
                        </div>
                      ) : schema?.type === 'enum' && schema.options ? (
                        <div className="flex items-center gap-2 flex-1">
                          <select
                            className="flex-1 h-8 text-xs rounded-md border bg-background px-2"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            autoFocus
                          >
                            {schema.options.map(o => (
                              <option key={o} value={o}>{o}</option>
                            ))}
                          </select>
                          <Button size="sm" onClick={handleSaveOverride} disabled={saving}>
                            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>取消</Button>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-1 flex-1">
                          <div className="flex items-center gap-2">
                            <Input
                              className="flex-1 h-8 text-xs"
                              type={schema?.type === 'int' || schema?.type === 'float' ? 'number' : 'text'}
                              min={schema?.min}
                              max={schema?.max}
                              step={schema?.type === 'float' ? '0.01' : '1'}
                              value={editValue}
                              onChange={(e) => { setEditValue(e.target.value); setEditError('') }}
                              onKeyDown={(e) => { if (e.key === 'Enter') handleSaveOverride() }}
                              autoFocus
                            />
                            <Button size="sm" onClick={handleSaveOverride} disabled={saving}>
                              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>取消</Button>
                          </div>
                          {editError && <p className="text-xs text-red-500">{editError}</p>}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center gap-2 flex-1">
                      <code className="text-xs bg-muted px-1.5 py-0.5 rounded min-w-[80px] text-center">
                        {friendlyValue(item) || '-'}
                      </code>
                      {schema?.type === 'int' || schema?.type === 'float' ? (
                        <span className="text-[10px] text-muted-foreground">
                          {schema.min !== undefined && schema.max !== undefined
                            ? `${schema.min}–${schema.max}`
                            : ''}
                        </span>
                      ) : null}
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
              )})}
            </div>
          </CardContent>
        </Card>
      </div>
      )}
    </div>
  )
}
