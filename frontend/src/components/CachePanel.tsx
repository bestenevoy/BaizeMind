import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { RefreshCw, Trash2, Database, Clock, AlertCircle, Eye, X } from 'lucide-react'
import {
  listCache, clearCache, deleteCacheEntry, getCacheEntry,
  type CacheListResponse, type CacheEntryDetail,
} from '@/lib/api'

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
  const [loading, setLoading] = useState(true)        // 首次加载 / 手动刷新时显示 skeleton
  const [refreshing, setRefreshing] = useState(false) // namespace 切换时的轻量指示
  const [error, setError] = useState('')
  const [filterNs, setFilterNs] = useState<string>('')  // 空 = 全部
  const [busy, setBusy] = useState(false)
  // 详情抽屉：点击列表项展开，显示完整 input + content 供 debug 分析
  const [detail, setDetail] = useState<CacheEntryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')

  // showSkeleton=true: 显示 skeleton（首次加载/手动刷新）
  // showSkeleton=false: 保留旧数据 + 轻量 refreshing 指示（namespace 切换）
  const fetchCache = useCallback(async (ns: string, showSkeleton: boolean) => {
    if (showSkeleton) {
      setLoading(true)
    } else {
      setRefreshing(true)
    }
    setError('')
    try {
      const r = await listCache(ns || undefined)
      setData(r)
    } catch (e: any) {
      setError(e?.message || String(e))
      if (showSkeleton) setData(null)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  // 首次挂载加载
  useEffect(() => {
    fetchCache('', true)
  }, [fetchCache])

  // 切换 namespace：不显示 skeleton，保留旧数据，只加轻量指示
  const switchNs = (ns: string) => {
    setFilterNs(ns)
    fetchCache(ns, false)
  }

  const handleClearAll = async () => {
    if (!confirm('⚠️ 清空所有缓存条目？此操作不可撤销！')) return
    if (!confirm('再次确认: 清空全部缓存？')) return
    setBusy(true)
    try {
      const r = await clearCache()
      alert(`已清空 ${r.cleared} 条缓存`)
      await fetchCache(filterNs, false)
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
      await fetchCache(filterNs, false)
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
      await fetchCache(filterNs, false)
    } catch (e: any) {
      alert(`删除失败: ${e?.message || e}`)
    }
  }

  const handleViewDetail = async (key: string) => {
    setDetailLoading(true)
    setDetailError('')
    setDetail(null)
    try {
      const d = await getCacheEntry(key)
      setDetail(d)
    } catch (e: any) {
      setDetailError(e?.message || String(e))
    } finally {
      setDetailLoading(false)
    }
  }

  const namespaces = data?.namespaces ? Object.keys(data.namespaces).sort() : []
  const enabled = data?.enabled ?? false

  // 按链路追踪 key（caller）分组，组内按 created_at 时间倒序（最新在前）
  // caller 标明在何处调用 LLM：nl2sql.generate_sql / answer_generator / query_router 等
  const groupedByCaller = (() => {
    if (!data?.entries?.length) return [] as Array<{ caller: string; entries: NonNullable<typeof data>['entries'] }>
    const sorted = [...data.entries].sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
    const groups = new Map<string, NonNullable<typeof data>['entries']>()
    for (const e of sorted) {
      const k = e.caller || '(unknown)'
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k)!.push(e)
    }
    return Array.from(groups.entries()).map(([caller, entries]) => ({ caller, entries }))
  })()

  // caller → 中文说明（标明 LLM 调用位置）
  const callerLabel: Record<string, string> = {
    'nl2sql.generate_sql': 'NL2SQL 生成 SQL 语句',
    'nl2sql.format_answer': 'NL2SQL 结果整理为自然语言',
    'answer_generator': '回答生成',
    'query_router': '查询路由分类',
    'entity_extractor': '实体抽取',
    'reranker': '重排序',
    'query_rewrite': '查询改写',
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto space-y-6">
      {/* 状态概览 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Database className="h-5 w-5" />
            缓存概览
          </CardTitle>
          <Button variant="outline" size="sm" onClick={() => fetchCache(filterNs, true)} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${(loading || refreshing) ? 'animate-spin' : ''}`} />
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

              {/* 操作区 */}
              <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t">
                <span className="text-xs text-muted-foreground mr-1">Namespace 过滤:</span>
                <Button
                  variant={filterNs === '' ? 'default' : 'outline'}
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => switchNs('')}
                >
                  全部
                </Button>
                {namespaces.map((ns) => (
                  <Button
                    key={ns}
                    variant={filterNs === ns ? 'default' : 'outline'}
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => switchNs(ns)}
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
            缓存条目{data ? (
              filterNs ? (
                <span className="text-sm font-normal text-muted-foreground ml-2">
                  {data.filtered_total} / {data.total}（已按 "{filterNs}" 筛选）
                </span>
              ) : (
                <span className="text-sm font-normal text-muted-foreground ml-2">
                  共 {data.total} 条
                </span>
              )
            ) : ''}
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
            <div className="space-y-4">
              {groupedByCaller.map(({ caller, entries }) => (
                <div key={caller} className="space-y-2">
                  {/* 分组标题：caller（链路追踪 key） + 调用位置说明 + 条目数 */}
                  <div className="flex items-center gap-2 px-1 sticky top-0 bg-background/80 backdrop-blur py-1 z-10">
                    <Badge variant="secondary" className="text-xs font-mono">
                      {caller}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      · {callerLabel[caller] || caller}
                    </span>
                    <span className="text-[10px] text-muted-foreground ml-auto">
                      {entries.length} 条 · 最新 {formatTime(entries[0]?.created_at)}
                    </span>
                  </div>
                  {entries.map((e) => (
                    <div
                      key={e.key}
                      className="p-2.5 rounded-lg border bg-card hover:bg-muted/30 transition-colors cursor-pointer"
                      onClick={() => handleViewDetail(e.key)}
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
                          className="h-6 w-6 shrink-0 text-muted-foreground hover:text-blue-500"
                          onClick={(ev) => { ev.stopPropagation(); handleViewDetail(e.key) }}
                          title="查看完整内容"
                        >
                          <Eye className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0 text-muted-foreground hover:text-red-500"
                          onClick={(ev) => { ev.stopPropagation(); handleDelete(e.key) }}
                          title="删除"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                      {/* value (LLM 响应) 预览 */}
                      <pre className="text-xs bg-muted/50 dark:bg-muted/20 rounded p-2 whitespace-pre-wrap break-all max-h-24 overflow-y-auto font-mono">
                        {e.value_preview}
                      </pre>
                      {/* input (给 LLM 的上下文) 预览 */}
                      {e.input_preview && (
                        <div className="mt-1.5">
                          <div className="flex items-center gap-1 mb-0.5 text-[10px] text-muted-foreground">
                            <span className="font-semibold">Input</span>
                            <span>({e.input_length} chars</span>
                            {e.has_full_input && <span className="text-green-600">· 完整</span>}
                            {!e.has_full_input && <span className="text-yellow-600">· 旧格式仅 preview</span>}
                            <span>)</span>
                          </div>
                          <pre className="text-[11px] bg-blue-50 dark:bg-blue-950/20 border-l-2 border-blue-200 dark:border-blue-800 rounded p-1.5 whitespace-pre-wrap break-all max-h-20 overflow-y-auto font-mono text-muted-foreground">
                            {e.input_preview}
                          </pre>
                        </div>
                      )}
                      <div className="flex items-center justify-between mt-1 text-[10px] text-muted-foreground">
                        <span>创建: {formatTime(e.created_at)}</span>
                        <span>value {e.value_length} bytes · input {e.input_length} chars</span>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 详情抽屉：点击列表项后从右侧滑出，展示完整 input + content */}
      {(detail || detailLoading || detailError) && (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-black/40"
          onClick={() => { setDetail(null); setDetailError('') }}
        >
          <div
            className="w-full max-w-3xl h-full bg-background shadow-xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 抽屉头部 */}
            <div className="sticky top-0 z-10 bg-background border-b p-4 flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <Eye className="h-4 w-4 shrink-0 text-blue-500" />
                <span className="font-semibold text-sm">缓存条目详情</span>
                {detail?.caller && (
                  <Badge variant="secondary" className="text-[10px] font-mono shrink-0">
                    {detail.caller}
                  </Badge>
                )}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => { setDetail(null); setDetailError('') }}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            {/* 抽屉内容 */}
            <div className="p-4 space-y-4">
              {detailLoading && <Skeleton className="h-40 w-full" />}
              {detailError && (
                <div className="flex items-center gap-2 text-sm text-red-500">
                  <AlertCircle className="h-4 w-4" />
                  {detailError}
                </div>
              )}
              {detail?.message && (
                <div className="flex items-center gap-2 text-sm text-yellow-600 bg-yellow-50 dark:bg-yellow-950/30 p-2 rounded">
                  <AlertCircle className="h-4 w-4" />
                  {detail.message}
                </div>
              )}
              {detail && !detail.message && (
                <>
                  {/* Meta 信息 */}
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">Namespace</div>
                      <div className="font-mono">{detail.namespace}</div>
                    </div>
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">Caller</div>
                      <div className="font-mono truncate">{detail.caller || '-'}</div>
                    </div>
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">Input 长度</div>
                      <div className="font-mono">{detail.input_length} chars</div>
                    </div>
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">Content 长度</div>
                      <div className="font-mono">{detail.content_length} bytes</div>
                    </div>
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">创建时间</div>
                      <div className="font-mono">{formatTime(detail.created_at)}</div>
                    </div>
                    <div className="p-2 rounded border">
                      <div className="text-muted-foreground">TTL 剩余</div>
                      <div className="font-mono">{formatTTL(detail.ttl_remaining)}</div>
                    </div>
                  </div>

                  {/* Key */}
                  <div>
                    <div className="text-xs font-semibold mb-1 text-muted-foreground">Key</div>
                    <code className="text-[11px] bg-muted p-2 rounded block break-all font-mono">
                      {detail.key}
                    </code>
                  </div>

                  {/* Input (给到 LLM 的实际上下文) */}
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <div className="text-xs font-semibold text-muted-foreground">
                        Input (给到 LLM 的实际上下文)
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[10px]"
                        onClick={() => navigator.clipboard?.writeText(detail.input)}
                      >
                        复制
                      </Button>
                    </div>
                    <pre className="text-xs bg-blue-50 dark:bg-blue-950/20 border-l-2 border-blue-200 dark:border-blue-800 rounded p-3 whitespace-pre-wrap break-all max-h-96 overflow-y-auto font-mono">
                      {detail.input || '(空 — 非 LLM namespace 或旧格式缓存无完整 input)'}
                    </pre>
                  </div>

                  {/* Content (LLM 响应) */}
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <div className="text-xs font-semibold text-muted-foreground">
                        Content (LLM 响应)
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[10px]"
                        onClick={() => navigator.clipboard?.writeText(detail.content)}
                      >
                        复制
                      </Button>
                    </div>
                    <pre className="text-xs bg-muted/50 dark:bg-muted/20 rounded p-3 whitespace-pre-wrap break-all max-h-96 overflow-y-auto font-mono">
                      {detail.content}
                    </pre>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
