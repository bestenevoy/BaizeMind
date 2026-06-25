import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { RefreshCw, Trash2, Database, Clock, AlertCircle } from 'lucide-react'
import { listCache, clearCache, deleteCacheEntry, type CacheListResponse } from '@/lib/api'

function formatTime(ts: number | null): string {
  if (ts === null || ts === undefined) return '永不过期'
  const d = new Date(ts * 1000)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function formatTTL(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '永久'
  if (seconds <= 0) return '已过期'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}

export function CachePanel() {
  const [data, setData] = useState<CacheListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterNs, setFilterNs] = useState<string>('')  // 空 = 全部
  const [busy, setBusy] = useState(false)

  const fetchCache = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await listCache(filterNs || undefined)
      setData(r)
    } catch (e: any) {
      setError(e?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filterNs])

  useEffect(() => {
    fetchCache()
  }, [fetchCache])

  const handleClearAll = async () => {
    if (!confirm('⚠️ 清空所有缓存条目？此操作不可撤销！')) return
    if (!confirm('再次确认: 清空全部缓存？')) return
    setBusy(true)
    try {
      const r = await clearCache()
      alert(`已清空 ${r.cleared} 条缓存`)
      await fetchCache()
    } catch (e: any) {
      alert(`清空失败: ${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const handleClearNs = async (ns: string) => {
    if (!confirm(`清空 namespace "${ns}" 下的所有缓存？`)) return
    setBusy(true)
    try {
      const r = await clearCache(ns)
      alert(`已清空 ${r.cleared} 条`)
      await fetchCache()
    } catch (e: any) {
      alert(`清空失败: ${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (key: string) => {
    if (!confirm('删除该缓存条目？')) return
    try {
      await deleteCacheEntry(key)
      await fetchCache()
    } catch (e: any) {
      alert(`删除失败: ${e?.message || e}`)
    }
  }

  const namespaces = data?.namespaces ? Object.keys(data.namespaces).sort() : []
  const enabled = data?.enabled ?? false

  return (
    <div className="flex-1 min-h-0 overflow-y-auto space-y-6">
      {/* 状态概览 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Database className="h-5 w-5" />
            缓存概览
          </CardTitle>
          <Button variant="outline" size="sm" onClick={fetchCache} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 text-sm text-red-500">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          ) : data ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-2xl font-bold tabular-nums">{data.total}</p>
                  <p className="text-xs text-muted-foreground">总条目</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-sm font-semibold">{data.backend}</p>
                  <p className="text-xs text-muted-foreground">后端</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-sm font-semibold">{formatTTL(data.ttl_seconds)}</p>
                  <p className="text-xs text-muted-foreground">默认 TTL</p>
                </div>
                <div className="p-3 rounded-lg border text-center">
                  <p className="text-sm font-semibold">
                    {enabled ? (
                      <Badge variant="default" className="bg-green-500">启用</Badge>
                    ) : (
                      <Badge variant="secondary">已禁用</Badge>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">状态</p>
                </div>
              </div>

              {data.message && (
                <div className="mt-3 flex items-center gap-2 text-xs text-yellow-600 bg-yellow-50 dark:bg-yellow-950/30 p-2 rounded">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {data.message}
                </div>
              )}

              {/* 子开关 */}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted-foreground">子开关:</span>
                <Badge variant={data.query_rewrite_enabled ? 'default' : 'secondary'}>
                  query_rewrite: {data.query_rewrite_enabled ? 'ON' : 'OFF'}
                </Badge>
              </div>

              {/* 操作区 */}
              <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t">
                <span className="text-xs text-muted-foreground mr-1">Namespace 过滤:</span>
                <Button
                  variant={filterNs === '' ? 'default' : 'outline'}
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setFilterNs('')}
                >
                  全部
                </Button>
                {namespaces.map((ns) => (
                  <Button
                    key={ns}
                    variant={filterNs === ns ? 'default' : 'outline'}
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => setFilterNs(ns)}
                  >
                    {ns} ({data.namespaces?.[ns] ?? 0})
                  </Button>
                ))}
                <div className="flex-1" />
                {filterNs && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs text-orange-600 border-orange-300 hover:bg-orange-50 dark:hover:bg-orange-950"
                    onClick={() => handleClearNs(filterNs)}
                    disabled={busy || !enabled}
                  >
                    <Trash2 className="h-3 w-3 mr-1" />
                    清空 "{filterNs}"
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950"
                  onClick={handleClearAll}
                  disabled={busy || !enabled || data.total === 0}
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  清空全部
                </Button>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>

      {/* 条目列表 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">
            缓存条目 {data ? `(${data.entries.length})` : ''}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : !enabled ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              缓存已全局禁用（settings.cache_enabled = false）
            </p>
          ) : data?.entries.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              {filterNs ? `namespace "${filterNs}" 下暂无缓存条目` : '暂无缓存条目'}
            </p>
          ) : (
            <div className="space-y-2">
              {data?.entries.map((e) => (
                <div
                  key={e.key}
                  className="p-2.5 rounded-lg border bg-card hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Badge variant="outline" className="text-[10px] font-mono">
                      {e.namespace || '(no-ns)'}
                    </Badge>
                    <code className="text-[10px] text-muted-foreground truncate flex-1" title={e.key}>
                      {e.key}
                    </code>
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground shrink-0">
                      <Clock className="h-3 w-3" />
                      {formatTTL(e.ttl_remaining)}
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0 text-muted-foreground hover:text-red-500"
                      onClick={() => handleDelete(e.key)}
                      title="删除"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  <pre className="text-xs bg-muted/50 dark:bg-muted/20 rounded p-2 whitespace-pre-wrap break-all max-h-32 overflow-y-auto font-mono">
                    {e.value_preview}
                  </pre>
                  <div className="flex items-center justify-between mt-1 text-[10px] text-muted-foreground">
                    <span>创建: {formatTime(e.created_at)}</span>
                    <span>{e.value_length} bytes</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
