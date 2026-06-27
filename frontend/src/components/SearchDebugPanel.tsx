import { useState, useEffect, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Loader2, ChevronDown, ChevronRight, Check, X, Eye, EyeOff, HelpCircle, Database, Brain, GitGraph, MessageSquare, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { searchDebug, updateConfigOverride, type SearchDebugResponse, type UnifiedSearchDebugResponse, type UnifiedDebugStep } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

// [UNIFIED] 类型守卫：区分统一流程响应与 doc/sql 调试响应
function isUnifiedResult(r: SearchDebugResponse | UnifiedSearchDebugResponse | null): r is UnifiedSearchDebugResponse {
  return r != null && 'mode' in r && r.mode === 'unified'
}

export function SearchDebugPanel({ folder, docId, tags, folderTree, tagFilter }: {
  folder: string | null; docId: string | null; tags: string[]
  folderTree: React.ReactNode; tagFilter: React.ReactNode
}) {
  const { isGuest, user } = useAuth()
  // 访客查询长度上限（与 chat 一致）
  const guestMax = user?.guest_chat_max_length ?? 200
  const maxLength = isGuest ? guestMax : undefined

  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchDebugResponse | UnifiedSearchDebugResponse | null>(null)
  const [error, setError] = useState('')
  const [expandedPreviews, setExpandedPreviews] = useState<Record<string, boolean>>({})
  const [resultTab, setResultTab] = useState<string>('rewrite')
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [showAll, setShowAll] = useState(true)
  const [queryFilter, setQueryFilter] = useState<number>(-1) // -1=汇总, 0..N-1=按改写 query 筛选
  const [forcePath, setForcePath] = useState<'unified' | 'doc' | 'sql'>('unified')
  const [searchParams, setSearchParams] = useSearchParams()

  // Check for pre-fetched data from chat (sessionStorage)
  useEffect(() => {
    const stored = sessionStorage.getItem('chat_retrieval_debug')
    if (stored) {
      try {
        const data = JSON.parse(stored) as SearchDebugResponse
        if (data.query) {
          setQuery(data.query)
          setResult(data)
        }
      } catch {}
      sessionStorage.removeItem('chat_retrieval_debug')
    }
  }, [])

  // Auto-search when coming from chat with a query param (without pre-fetched data)
  const qParam = searchParams.get('q')
  useEffect(() => {
    if (qParam && qParam.trim() && !result) {
      const trimmed = qParam.trim()
      setQuery(trimmed)
      const newParams = new URLSearchParams(searchParams)
      newParams.delete('q')
      setSearchParams(newParams, { replace: true })
      handleSearch(trimmed)
    }
  }, [qParam])

  const togglePreview = (key: string) => {
    setExpandedPreviews(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSearch = async (q?: string) => {
    const searchQuery = (q || query).trim()
    if (!searchQuery || loading) return
    if (maxLength && searchQuery.length > maxLength) {
      setError(`访客模式下单次查询不能超过 ${maxLength} 字符，请登录后继续使用。`)
      return
    }
    setError('')
    setLoading(true)
    setResult(null)
    setExpandedPreviews({})
    setResultTab('rewrite')
    setQueryFilter(-1)
    try {
      const res = await searchDebug(searchQuery, folder, tags, docId, undefined, forcePath)
      setResult(res)
      // [UNIFIED] 统一流程模式不需要切 tab（直接展示 steps 列表）
      // doc/sql 模式：切到 SQL 路径时重置 tab
      if ('mode' in res && res.mode === 'unified') {
        setResultTab('trace')
      } else if (res.query_type === 'sql_query') {
        setResultTab('sql')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      console.error('Search debug failed:', err)
    } finally {
      setLoading(false)
    }
  }

  const startEdit = (key: string, currentValue: number) => {
    setEditingKey(key)
    setEditValue(String(currentValue))
  }

  const saveEdit = async () => {
    if (!editingKey || saving) return
    const num = parseFloat(editValue)
    if (isNaN(num)) return
    setSaving(true)
    try {
      await updateConfigOverride(editingKey, editValue)
      setEditingKey(null)
      handleSearch()
    } catch (err) {
      console.error('Save config failed:', err)
    } finally {
      setSaving(false)
    }
  }

  const ThresholdValue = ({ label, configKey, value, hint }: { label: string; configKey: string; value: number; hint?: string }) => (
    <>
      <span className="text-muted-foreground" title={hint}>{label}:</span>
      {editingKey === configKey ? (
        <span className="flex items-center gap-1">
          <Input
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditingKey(null) }}
            onBlur={saveEdit}
            className="h-6 w-16 font-mono text-xs px-1"
            autoFocus
            disabled={saving}
          />
        </span>
      ) : (
        <button
          onClick={() => startEdit(configKey, value)}
          className="font-mono font-semibold hover:text-primary cursor-pointer border-b border-dashed border-muted-foreground/30 hover:border-primary"
          title="点击修改"
        >
          {value}
        </button>
      )}
    </>
  )

  const filterInfo = []
  if (docId) filterInfo.push(`文档: ${docId}`)
  else if (folder) filterInfo.push(`文件夹: ${folder}`)
  if (tags.length) filterInfo.push(`标签: ${tags.join(', ')}`)
  if (!docId && !folder && !tags.length) filterInfo.push('全部文档')
  // [UNIFIED] 统一流程模式无 stages/dense_threshold 等字段，doc/sql 模式才计算
  const docResult = !isUnifiedResult(result) ? result : null
  // Dense 召回去重并集 chunk 数：multi 模式用后端计算的 dense_union_count（所有 Q 完整召回去重）；
  // 单 query 模式取 dense_top5.length
  const denseUnionCount = docResult?.multi_query
    ? (docResult.dense_union_count ?? 0)
    : (docResult?.stages?.dense_top5?.length ?? 0)

  return (
    <Card className="p-4 text-sm h-full flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-3 flex-none">
        <Search className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">检索测试</span>
        <div className="flex gap-1">
          {filterInfo.map((f, i) => (
            <Badge key={i} variant="secondary" className="text-xs">{f}</Badge>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1 min-h-0">
        <div className="lg:col-span-3 space-y-3 overflow-y-auto border-r pr-3">
          {folderTree}
          {tagFilter}
        </div>

        <div className="lg:col-span-9 flex flex-col min-h-0">
          {isGuest && (
            <div className="flex items-center justify-between mb-1.5 text-[11px] text-muted-foreground">
              <span>访客模式：仅用于展示</span>
              <span className={query.length > (maxLength ?? 0) ? 'text-destructive' : ''}>
                {query.length}/{maxLength}
              </span>
            </div>
          )}
          <div className="flex gap-2 flex-none">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
              placeholder={isGuest ? '访客模式：输入查询文本（受字数限制）' : '输入查询文本，测试检索召回效果...'}
              className="flex-1"
              maxLength={maxLength}
            />
            <select
              value={forcePath}
              onChange={(e) => setForcePath(e.target.value as 'unified' | 'doc' | 'sql')}
              className="text-xs border rounded px-1.5 py-1 bg-background"
              title="调试模式：unified=复用主工作流完整流程；doc=仅文本 RAG 独立调用；sql=仅 NL2SQL 独立调用"
            >
              <option value="unified">统一流程</option>
              <option value="doc">文本RAG</option>
              <option value="sql">NL2SQL</option>
            </select>
            <Button
              onClick={() => handleSearch()}
              disabled={loading || !query.trim() || (!!maxLength && query.length > maxLength)}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Search className="h-4 w-4 mr-1" />}
              检索
            </Button>
          </div>
          {error && <p className="text-xs text-destructive mt-2">{error}</p>}

          {/* [UNIFIED] 统一流程模式：展示完整执行轨迹（与 chat 流程一致） */}
          {result && isUnifiedResult(result) && (
            <UnifiedTraceView result={result} />
          )}

          {/* doc / sql 调试模式：原有 stages/sql_debug 渲染 */}
          {result && !isUnifiedResult(result) && (
            <div className="mt-3 flex-1 min-h-0 flex flex-col space-y-3">
              {/* 第一行：可编辑配置项（点击数值修改） */}
              <div className="flex items-center gap-3 text-sm bg-muted/30 rounded p-2 flex-wrap flex-none">
                <ThresholdValue label="Dense 阈值" configKey="dense_vector_threshold" value={result.dense_threshold} hint="Dense 向量相似度下限，低于此值的候选被丢弃" />
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="Rerank 阈值" configKey="reranker_score_threshold" value={result.rerank_threshold || 0} hint="Rerank 分数下限，低于此值的候选不进入最终结果" />
                <span className="text-muted-foreground">|</span>
                <span className="flex items-center gap-0.5">
                  <ThresholdValue label="RRF 平滑常数" configKey="hybrid_rrf_k" value={result.rrf_k} hint="RRF 融合公式参数 k，值越大排名越平滑" />
                  <span title={"RRF 融合公式:\n\nscore(d) = Σ  w_i / (k + rank_i(d) + 1)\n\n  k: 平滑常数（此处可编辑）\n  w_i: 第 i 个检索源的权重（Dense/BM25）\n  rank_i(d): 文档 d 在第 i 个源中的排名（从 0 开始）\n\n归一化: normalized = score(d) / max_score\n\nk 越大 → 头部优势衰减，排名越平滑\nk 越小 → 头部优势放大，更看重高排名"}>
                    <HelpCircle className="h-3 w-3 text-muted-foreground/70 hover:text-foreground cursor-help" />
                  </span>
                </span>
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="预取倍数" configKey="retrieval_over_fetch_multiplier" value={result.over_fetch_multiplier} hint="Dense/BM25 各预取 RRF Top-K × 此倍数 条候选，再经 RRF 融合 + Rerank 缩减" />
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="RRF Top-K" configKey="hybrid_top_k" value={result.top_k} hint="RRF 融合后截断到此数，送入 Reranker" />
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="Rerank 输出数" configKey="rerank_top_k" value={result.rerank_top_k} hint="Reranker 实际输出的最大数量（再按 Rerank 阈值过滤得到最终结果）" />
                {editingKey && saving && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
              </div>

              {/* 第二行：检索流程对照（按 query_type 区分 doc / sql 路径） */}
              <div className="flex items-center gap-2 text-xs flex-none px-1 flex-wrap">
                <span className="text-muted-foreground font-medium">流程对照:</span>

                {result.query_type === 'sql_query' && result.sql_debug ? (
                  <>
                    {/* SQL 路径：向量召回 → 多表选择 → NL2SQL → 执行 */}
                    <span className="text-muted-foreground">
                      向量召回
                      <span className="font-mono font-semibold text-foreground"> {result.sql_debug.recalled_sheets.length} </span>
                      Sheet
                    </span>
                    <span className="text-muted-foreground">→</span>
                    <span className="text-muted-foreground">
                      多表选择
                      {result.sql_debug.selected_sheet ? (
                        <> 命中 <span className="font-mono text-foreground">{result.sql_debug.selected_sheet.sheet_name}</span></>
                      ) : (
                        <span className="font-mono font-semibold text-red-500"> 未命中 </span>
                      )}
                    </span>
                    <span className="text-muted-foreground">→</span>
                    <span className="text-muted-foreground">
                      NL2SQL
                      {result.sql_debug.sql ? (
                        <span className="font-mono font-semibold text-foreground"> 已生成 </span>
                      ) : (
                        <span className="font-mono font-semibold text-red-500"> 失败 </span>
                      )}
                    </span>
                    <span className="text-muted-foreground">→</span>
                    <span className="text-muted-foreground">
                      执行结果
                      {result.sql_debug.error ? (
                        <span className="font-mono font-semibold text-red-500"> 报错 </span>
                      ) : (
                        <span className={`font-mono font-semibold ${result.sql_debug.sql_result_row_count === 0 ? 'text-red-500' : 'text-primary'}`}> {result.sql_debug.sql_result_row_count} </span>
                      )}
                      行
                    </span>
                    {result.sql_debug.attempts.length > 0 && (
                      <span className="text-amber-500">(重试 {result.sql_debug.attempts.length} 次)</span>
                    )}
                    {result.sql_debug.fallback_reason && (
                      <span className="text-red-400">— {result.sql_debug.fallback_reason}</span>
                    )}
                    {result.sql_debug.error && (
                      <span className="text-red-400">— {result.sql_debug.error}</span>
                    )}
                  </>
                ) : (
                  <>
                    {/* 文档 RAG 路径：预取 → RRF → Rerank → 最终 */}
                    {/* 阶段1: 预取 */}
                    <span className="text-muted-foreground">
                      预取
                      <span className="font-mono text-foreground"> {result.over_fetch_multiplier}×{result.top_k}={result.over_fetch_multiplier * result.top_k} </span>
                      /源 (预取倍数×RRF Top-K)
                    </span>
                    <span className="text-muted-foreground">→</span>

                    {/* 阶段2: RRF 融合后 */}
                    <span className="text-muted-foreground">
                      RRF融合后
                      <span className="font-mono font-semibold text-foreground"> {result.stages.rrf.length} </span>
                      条
                    </span>
                    <span className="text-muted-foreground">→</span>

                    {/* 阶段3: 送入 Reranker（受 检索返回数 限制） */}
                    <span className="text-muted-foreground">
                      送入Rerank
                      <span className="font-mono text-foreground"> ≤{result.top_k} </span>
                      (RRF Top-K)
                    </span>
                    <span className="text-muted-foreground">→</span>

                    {/* 阶段4: Rerank 输出（受 Rerank 输出数 限制） */}
                    <span className="text-muted-foreground">
                      Rerank输出
                      <span className="font-mono font-semibold text-foreground"> {result.stages.rerank.length} </span>
                      条
                      <span className="text-muted-foreground/70"> (≤{result.rerank_top_k})</span>
                    </span>
                    <span className="text-muted-foreground">→</span>

                    {/* 阶段5: 最终（受 Rerank 阈值过滤） */}
                    <span className="text-muted-foreground">
                      最终
                      <span className={`font-mono font-semibold ${result.final_count === 0 ? 'text-red-500' : 'text-primary'}`}> {result.final_count} </span>
                      条
                    </span>

                    {result.filtered_out_by_rerank_threshold > 0 && (
                      <span className="text-red-400">(Rerank阈值过滤 {result.filtered_out_by_rerank_threshold} 条)</span>
                    )}
                    {result.final_count === 0 && (
                      <span className="text-red-400">— 所有结果被阈值过滤！点击上方数值修改</span>
                    )}
                    <div className="flex-1" />
                    <button
                      onClick={() => setShowAll(!showAll)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0"
                    >
                      {showAll ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                      {showAll ? '仅通过阈值' : '显示全部'}
                    </button>
                  </>
                )}
              </div>

              <div className="flex-1 min-h-0 flex flex-col">
                <div className="flex gap-0 border-b flex-none">
                  {(result.query_type === 'sql_query' ? [
                    { key: 'sql', label: `NL2SQL ${result.sql_debug ? `(${result.sql_debug.sql_result_row_count}行)` : ''}` },
                  ] : [
                    { key: 'rewrite', label: '查询改写' },
                    { key: 'rrf', label: `RRF融合 (${result.stages.rrf.length})` },
                    { key: 'rerank', label: `Reranker (${result.stages.rerank.length})` },
                    { key: 'dense', label: `Dense向量 (${denseUnionCount})` },
                    { key: 'bm25', label: `BM25 (${result.stages.bm25_top5.length})` },
                  ]).map(t => (
                    <button
                      key={t.key}
                      onClick={() => setResultTab(t.key)}
                      className={`px-3 py-1.5 text-xs border-b-2 transition-colors ${
                        resultTab === t.key
                          ? 'border-primary text-primary font-medium'
                          : 'border-transparent text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>

                <div className="flex-1 min-h-0 overflow-y-auto pt-2">
                  {resultTab === 'rewrite' && (
                    <div className="space-y-4">
                      {result.rewrite.enabled ? (
                        <>
                          {(result.multi_query && result.rewrite.dense_queries && result.rewrite.dense_queries.length > 0) ? (
                            <>
                              <div className="text-xs text-muted-foreground">
                                Multi-Query Retrieval：Q0 为原始查询 + 改写出
                                <span className="font-mono font-semibold text-foreground mx-1">{result.rewrite.dense_queries.length - 1}</span>
                                条等价 Dense Query + 1 条共享 BM25 Query（全部参与 RRF 融合，Rerank 使用原始查询）
                              </div>
                              {result.rewrite.dense_queries.map((p) => {
                                const isOrig = p.index === 0 && p.dense_query === result.rewrite.original
                                return (
                                <div key={p.index} className="space-y-2 border rounded p-2">
                                  <div className="flex items-center gap-1.5">
                                    {isOrig ? (
                                      <Badge variant="outline" className="text-xs font-mono bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-300">Q0 · 原始</Badge>
                                    ) : (
                                      <Badge variant="secondary" className="text-xs font-mono">Q{p.index}</Badge>
                                    )}
                                    <span className="text-xs text-muted-foreground">{isOrig ? '原始查询（参与召回兜底）' : `Dense 改写 #${p.index}`}</span>
                                  </div>
                                  <div className="bg-cyan-50 dark:bg-cyan-950/30 rounded p-2 space-y-1">
                                    <pre className="text-sm whitespace-pre-wrap break-all">{p.dense_query}</pre>
                                    <div className="flex flex-wrap gap-1">
                                      {p.dense_tokens.map((t, i) => (
                                        <Badge key={i} variant="outline" className="text-xs font-mono bg-cyan-50 dark:bg-cyan-950/30">{t}</Badge>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                                )
                              })}
                              <div className="bg-emerald-50 dark:bg-emerald-950/20 rounded p-3 space-y-1">
                                <div className="text-xs font-medium text-emerald-600 dark:text-emerald-400 mb-2">共享 BM25 查询（关键词检索用）</div>
                                <pre className="text-sm whitespace-pre-wrap break-all">{result.rewrite.bm25_query}</pre>
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {result.rewrite.bm25_tokens.map((t, i) => (
                                    <Badge key={i} variant="outline" className="text-xs font-mono bg-emerald-50 dark:bg-emerald-950/30">{t}</Badge>
                                  ))}
                                </div>
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="bg-cyan-50 dark:bg-cyan-950/30 rounded p-3 space-y-1">
                                <div className="text-xs font-medium text-cyan-700 dark:text-cyan-300 mb-2">Dense 查询（语义检索用）</div>
                                <pre className="text-sm whitespace-pre-wrap break-all">{result.rewrite.dense_query}</pre>
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {result.rewrite.dense_tokens.map((t, i) => (
                                    <Badge key={i} variant="outline" className="text-xs font-mono bg-cyan-50 dark:bg-cyan-950/30">{t}</Badge>
                                  ))}
                                </div>
                              </div>
                              <div className="bg-emerald-50 dark:bg-emerald-950/20 rounded p-3 space-y-1">
                                <div className="text-xs font-medium text-emerald-600 dark:text-emerald-400 mb-2">BM25 查询（关键词检索用）</div>
                                <pre className="text-sm whitespace-pre-wrap break-all">{result.rewrite.bm25_query}</pre>
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {result.rewrite.bm25_tokens.map((t, i) => (
                                    <Badge key={i} variant="outline" className="text-xs font-mono bg-emerald-50 dark:bg-emerald-950/30">{t}</Badge>
                                  ))}
                                </div>
                              </div>
                            </>
                          )}
                        </>
                      ) : (
                        <div className="text-sm text-muted-foreground text-center py-8">
                          查询改写已禁用（query_rewrite_enabled = false）
                        </div>
                      )}
                    </div>
                  )}
                  {resultTab === 'rrf' && (
                    <div className="space-y-1">
                      {result.multi_query && result.rewrite.dense_queries && result.rewrite.dense_queries.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap mb-1 pb-1 border-b">
                          <span className="text-xs text-muted-foreground">按 Query 筛选:</span>
                          <button onClick={() => setQueryFilter(-1)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === -1 ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}>汇总</button>
                          {result.rewrite.dense_queries.map((p) => {
                            const isOrig = p.index === 0 && p.dense_query === result.rewrite.original
                            return (
                              <button key={p.index} onClick={() => setQueryFilter(p.index)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === p.index ? 'bg-primary text-primary-foreground border-primary' : isOrig ? 'border-amber-300 text-amber-700 dark:text-amber-300' : 'border-border text-muted-foreground hover:text-foreground'}`} title={p.dense_query}>
                                {isOrig ? `Q0·原始` : `Q${p.index}`}
                              </button>
                            )
                          })}
                        </div>
                      )}
                      {result.stages.rrf.map((c, i) => {
                        if (queryFilter >= 0 && !(c.source_queries ?? []).includes(queryFilter)) return null
                        return (
                        <div key={i} className="rounded p-2 border bg-muted/20 border-border">
                          <div className="flex items-center gap-1.5">
                            <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                            <span className="text-xs break-all" title={`${c.filename || c.doc_id} / ${c.chunk_id}`}>
                              <span className="font-medium">{c.filename || c.doc_id}</span>
                              <span className="text-muted-foreground ml-1 font-mono">/ {c.chunk_id}</span>
                            </span>
                            {result.multi_query && (c.source_queries ?? []).length > 0 && (
                              <span className="flex gap-0.5">
                                {c.source_queries!.map(qi => {
                                  const isOrig = qi === 0 && result.rewrite.original === (result.rewrite.dense_queries?.[0]?.dense_query ?? '')
                                  return <Badge key={qi} variant="outline" className={`text-xs font-mono px-1 py-0 ${isOrig ? 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-300' : ''}`}>{isOrig ? 'Q0·原' : `Q${qi}`}</Badge>
                                })}
                              </span>
                            )}
                            <span className="ml-auto font-mono text-xs shrink-0">RRF: {c.rrf_normalized}</span>
                          </div>
                          <div className="flex gap-3 mt-0.5 text-xs text-muted-foreground/50 font-mono">
                            <span>Dense: {c.dense_score?.toFixed(4) || '-'}</span>
                            <span>BM25: {c.bm25_score?.toFixed(4) || '-'}</span>
                            <span className="text-muted-foreground/30 truncate" title={c.doc_id}>doc: {c.doc_id}</span>
                          </div>
                          <button onClick={() => togglePreview(`rrf-${i}`)} className="text-xs text-primary/70 hover:text-primary mt-0.5">
                            {expandedPreviews[`rrf-${i}`] ? '收起' : '展开'}文本
                          </button>
                          {expandedPreviews[`rrf-${i}`] && (
                            <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-all overflow-y-auto">{c.text_preview}</p>
                          )}
                        </div>
                      )})}
                    </div>
                  )}
                  {resultTab === 'rerank' && (
                    <div className="space-y-1">
                      {result.multi_query && result.rewrite.dense_queries && result.rewrite.dense_queries.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap mb-1 pb-1 border-b">
                          <span className="text-xs text-muted-foreground">按 Query 筛选:</span>
                          <button onClick={() => setQueryFilter(-1)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === -1 ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}>汇总</button>
                          {result.rewrite.dense_queries.map((p) => {
                            const isOrig = p.index === 0 && p.dense_query === result.rewrite.original
                            return (
                              <button key={p.index} onClick={() => setQueryFilter(p.index)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === p.index ? 'bg-primary text-primary-foreground border-primary' : isOrig ? 'border-amber-300 text-amber-700 dark:text-amber-300' : 'border-border text-muted-foreground hover:text-foreground'}`} title={p.dense_query}>
                                {isOrig ? `Q0·原始` : `Q${p.index}`}
                              </button>
                            )
                          })}
                        </div>
                      )}
                      {result.stages.rerank.map((c, i) => {
                        if (queryFilter >= 0 && !(c.source_queries ?? []).includes(queryFilter)) return null
                        if (!showAll && !c.rerank_pass_threshold) return null
                        return (
                        <div key={i} className={`rounded p-2 border ${c.rerank_pass_threshold ? 'bg-muted/20 border-border' : 'bg-red-50 dark:bg-red-950/10 border-red-200 dark:border-red-800'}`}>
                          <div className="flex items-center gap-1.5">
                            <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                            <span className="text-xs break-all" title={`${c.filename || c.doc_id} / ${c.chunk_id}`}>
                              <span className="font-medium">{c.filename || c.doc_id}</span>
                              <span className="text-muted-foreground ml-1 font-mono">/ {c.chunk_id}</span>
                            </span>
                            {result.multi_query && (c.source_queries ?? []).length > 0 && (
                              <span className="flex gap-0.5">
                                {c.source_queries!.map(qi => {
                                  const isOrig = qi === 0 && result.rewrite.original === (result.rewrite.dense_queries?.[0]?.dense_query ?? '')
                                  return <Badge key={qi} variant="outline" className={`text-xs font-mono px-1 py-0 ${isOrig ? 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-300' : ''}`}>{isOrig ? 'Q0·原' : `Q${qi}`}</Badge>
                                })}
                              </span>
                            )}
                            <span className="ml-auto font-mono text-xs shrink-0">score: {c.rerank_score}</span>
                            {c.rerank_pass_threshold ? (
                              <Check className="h-3 w-3 text-green-500 shrink-0" />
                            ) : (
                              <X className="h-3 w-3 text-red-400 shrink-0" />
                            )}
                          </div>
                          <button onClick={() => togglePreview(`rerank-${i}`)} className="text-xs text-primary/70 hover:text-primary mt-0.5">
                            {expandedPreviews[`rerank-${i}`] ? '收起' : '展开'}文本
                          </button>
                          {expandedPreviews[`rerank-${i}`] && (
                            <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-all overflow-y-auto">{c.text_preview}</p>
                          )}
                        </div>
                      )})}
                    </div>
                  )}
                  {resultTab === 'dense' && (
                    <div>
                      {result.multi_query && result.stages.per_query && result.stages.per_query.length > 0 ? (
                        <>
                          <div className="flex items-center gap-1 flex-wrap mb-1 pb-1 border-b">
                            <span className="text-xs text-muted-foreground">按 Query 筛选:</span>
                            <button onClick={() => setQueryFilter(-1)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === -1 ? 'bg-primary text-primary-foreground border-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}>汇总</button>
                            {result.stages.per_query.map((q) => {
                              const isOrig = q.index === 0 && q.dense_query === result.rewrite.original
                              return (
                                <button key={q.index} onClick={() => setQueryFilter(q.index)} className={`px-2 py-0.5 rounded text-xs border ${queryFilter === q.index ? 'bg-primary text-primary-foreground border-primary' : isOrig ? 'border-amber-300 text-amber-700 dark:text-amber-300' : 'border-border text-muted-foreground hover:text-foreground'}`} title={q.dense_query}>
                                  {isOrig ? `Q0·原始` : `Q${q.index}`}
                                </button>
                              )
                            })}
                          </div>
                          {queryFilter === -1 ? (
                            // 汇总状态：用去重并集列表，按行显示（与 RRF/Rerank 风格一致）
                            <div className="space-y-0.5">
                              {result.stages.dense_top5.map((c, i) => {
                                const s = c.score ?? 0
                                const pass = (result.dense_threshold || result.threshold) != null ? s >= (result.dense_threshold || result.threshold) : null
                                if (!showAll && pass === false) return null
                                return (
                                <div key={i} className={`rounded p-1.5 ${pass === false ? 'bg-red-50 dark:bg-red-950/10 border border-red-200 dark:border-red-800' : pass === true ? 'bg-green-50 dark:bg-green-950/10 border border-green-200 dark:border-green-800' : 'bg-muted/20'}`}>
                                  <div className="flex items-center gap-1">
                                    <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                                    <span className="text-xs break-all" title={`${c.filename || c.doc_id} / ${c.chunk_id}`}>
                                      <span className="font-medium">{c.filename || c.doc_id}</span>
                                      <span className="text-muted-foreground ml-1 font-mono">/ {c.chunk_id}</span>
                                    </span>
                                    {(c.source_queries ?? []).length > 0 && (
                                      <span className="flex gap-0.5">
                                        {c.source_queries!.map(qi => {
                                          const isOrig = qi === 0 && result.rewrite.original === (result.rewrite.dense_queries?.[0]?.dense_query ?? '')
                                          return <Badge key={qi} variant="outline" className={`text-xs font-mono px-1 py-0 ${isOrig ? 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-300' : ''}`}>{isOrig ? 'Q0·原' : `Q${qi}`}</Badge>
                                        })}
                                      </span>
                                    )}
                                    <span className="ml-auto font-mono text-xs shrink-0">score: {s}</span>
                                    {pass !== null && (
                                      pass ? <Check className="h-3 w-3 text-green-500 shrink-0" /> : <X className="h-3 w-3 text-red-400 shrink-0" />
                                    )}
                                  </div>
                                  <button onClick={() => togglePreview(`dense-${i}`)} className="text-xs text-primary/70 hover:text-primary">
                                    {expandedPreviews[`dense-${i}`] ? '收起' : '展开'}文本
                                  </button>
                                  {expandedPreviews[`dense-${i}`] && (
                                    <p className="mt-0.5 text-xs text-muted-foreground whitespace-pre-wrap break-all overflow-y-auto">{c.text_preview}</p>
                                  )}
                                </div>
                              )})}
                            </div>
                          ) : (
                            // 筛选某 Q：显示该 Q 的 dense_top
                            <div className="space-y-3">
                              {result.stages.per_query
                                .filter((q) => q.index === queryFilter)
                                .map((q) => {
                                  const isOriginal = q.index === 0 && q.dense_query === result.rewrite.original
                                  return (
                                  <div key={q.index}>
                                    <div className="text-xs font-medium text-muted-foreground mb-1">
                                      {isOriginal ? (
                                        <><Badge variant="outline" className="text-xs font-mono mr-1 bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-300">Q0 · 原始</Badge> Dense ({q.dense_count})</>
                                      ) : (
                                        <><Badge variant="secondary" className="text-xs font-mono mr-1">Q{q.index}</Badge> Dense ({q.dense_count})</>
                                      )}
                                      <span className="font-normal text-muted-foreground/70 truncate ml-1">{q.dense_query}</span>
                                    </div>
                                    <StageMini label="" items={q.dense_top.map(c => ({ ...c, score: c.score ?? 0 }))} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix={`dense-q${q.index}`} scoreThreshold={result.dense_threshold || result.threshold} showAll={showAll} />
                                  </div>
                                  )
                                })}
                            </div>
                          )}
                        </>
                      ) : (
                        <StageMini label="" items={result.stages.dense_top5.map(c => ({ ...c, score: c.score ?? 0 }))} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="dense" scoreThreshold={result.dense_threshold || result.threshold} showAll={showAll} />
                      )}
                    </div>
                  )}
                  {resultTab === 'bm25' && (
                    <div>
                      {result.multi_query && result.rewrite.bm25_query && (
                        <div className="text-xs text-muted-foreground mb-1">共享 BM25 查询: <span className="font-mono text-foreground">{result.rewrite.bm25_query}</span></div>
                      )}
                      <StageMini label="" items={result.stages.bm25_top5} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="bm25" />
                    </div>
                  )}
                  {resultTab === 'sql' && result.query_type === 'sql_query' && result.sql_debug && (
                    <SqlDebugView sqlDebug={result.sql_debug} />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

// ── [UNIFIED] 统一流程轨迹视图：展示完整执行轨迹（与 chat 流程一致） ──

const NODE_ICON: Record<string, typeof Brain> = {
  query_router: Brain,
  retrieval_agent: Search,
  lightrag_agent: GitGraph,
  graph_agent: GitGraph,
  sql_agent: Database,
  answer_generator: MessageSquare,
  chitchat: MessageSquare,
}

const NODE_COLOR: Record<string, string> = {
  query_router: 'text-blue-500',
  retrieval_agent: 'text-cyan-500',
  lightrag_agent: 'text-purple-500',
  graph_agent: 'text-purple-500',
  sql_agent: 'text-indigo-500',
  answer_generator: 'text-emerald-500',
  chitchat: 'text-amber-500',
}

function UnifiedTraceView({ result }: { result: UnifiedSearchDebugResponse }) {
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({})
  const [expandedDocs, setExpandedDocs] = useState<Record<string, boolean>>({})

  const toggleStep = (i: number) => setExpandedSteps(prev => ({ ...prev, [i]: !prev[i] }))
  const toggleDoc = (key: string) => setExpandedDocs(prev => ({ ...prev, [key]: !prev[key] }))

  // 找到最终答案步（最后一个非 intermediate 的 answer_generator 或 chitchat）
  const finalStep = [...result.steps].reverse().find(s =>
    (s.node === 'answer_generator' && !s.intermediate) || s.node === 'chitchat'
  )
  // [TYPEFIX] finalStep.result 是 Record<string, unknown>，需预先转为 string 避免 unknown 泄漏到 JSX
  const finalAnswerText = finalStep ? String(finalStep.result.final_answer || finalStep.result.answer || '') : ''

  return (
    <div className="mt-3 flex-1 min-h-0 flex flex-col space-y-3">
      {/* 顶部摘要：query_type / sql_triggered / retrieval_path / error */}
      <div className="flex items-center gap-2 text-xs flex-wrap flex-none bg-muted/30 rounded p-2">
        <Badge variant="outline" className="text-xs font-mono">query_type: {result.query_type}</Badge>
        {result.sql_triggered ? (
          <Badge variant="default" className="text-xs bg-indigo-500 hover:bg-indigo-500">
            <Zap className="h-3 w-3 mr-1" />SQL Tool Call 已触发
          </Badge>
        ) : (
          <Badge variant="secondary" className="text-xs">未触发 SQL</Badge>
        )}
        {result.retrieval_path && (
          <Badge variant="outline" className="text-xs">retrieval_path: {result.retrieval_path}</Badge>
        )}
        <span className="text-muted-foreground">|</span>
        <span className="text-muted-foreground">共 {result.steps.length} 步</span>
        {result.error && (
          <span className="text-destructive">错误: {result.error}</span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-0">
        {result.steps.map((step, i) => {
          const Icon = NODE_ICON[step.node] || MessageSquare
          const color = NODE_COLOR[step.node] || 'text-muted-foreground'
          const isSqlTrigger = step.node === 'answer_generator' && step.intermediate && step.result.rerouted_to_sql === true
          const isIntermediate = step.intermediate
          const hasDetail = hasStepDetail(step)
          const isLast = i === result.steps.length - 1

          return (
            <div key={i} className="relative pl-6 pb-3">
              {/* 时间线竖线（除最后一个外） */}
              {!isLast && (
                <div className="absolute left-[11px] top-6 bottom-0 w-px bg-border" />
              )}
              {/* 时间线圆点 */}
              <div className={`absolute left-1 top-1 w-5 h-5 rounded-full flex items-center justify-center bg-background border-2 ${step.status === 'error' ? 'border-red-400' : isSqlTrigger ? 'border-amber-400' : 'border-border'}`}>
                <Icon className={`h-3 w-3 ${color}`} />
              </div>

              {/* 步骤卡片 */}
              <div className={`rounded border p-2 ${step.status === 'error' ? 'border-red-300 bg-red-50 dark:bg-red-950/10' : isSqlTrigger ? 'border-amber-300 bg-amber-50 dark:bg-amber-950/10' : isIntermediate ? 'border-muted-foreground/30 bg-muted/20' : 'border-border bg-card'}`}>
                {/* 第一行：节点名 + 状态 */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{step.label}</span>
                  <span className="text-xs text-muted-foreground font-mono">{step.node}</span>
                  <span className="text-xs text-muted-foreground">— {step.detail}</span>
                  {step.status === 'error' ? (
                    <Badge variant="destructive" className="text-[10px] ml-auto">错误</Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[10px] ml-auto">done</Badge>
                  )}
                  {isSqlTrigger && (
                    <Badge variant="outline" className="text-[10px] bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-400">
                      <Zap className="h-2.5 w-2.5 mr-0.5" />条件触发 SQL
                    </Badge>
                  )}
                  {isIntermediate && !isSqlTrigger && (
                    <Badge variant="outline" className="text-[10px] bg-muted">中间态</Badge>
                  )}
                </div>

                {/* 第二行：节点摘要（始终展示） */}
                <StepSummary step={step} />

                {/* 错误信息 */}
                {step.error && (
                  <p className="text-xs text-destructive mt-1">{step.error}</p>
                )}

                {/* 可展开详情 */}
                {hasDetail && (
                  <button
                    onClick={() => toggleStep(i)}
                    className="text-xs text-primary/70 hover:text-primary mt-1"
                  >
                    {expandedSteps[i] ? '收起详情' : '展开详情'}
                  </button>
                )}
                {expandedSteps[i] && hasDetail && (
                  <StepDetail step={step} expandedDocs={expandedDocs} onToggleDoc={toggleDoc} />
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* 最终答案 */}
      {finalStep && finalAnswerText && (
        <div className="flex-none border rounded p-3 bg-emerald-50 dark:bg-emerald-950/10 border-emerald-200 dark:border-emerald-800">
          <div className="flex items-center gap-1.5 mb-1">
            <MessageSquare className="h-3.5 w-3.5 text-emerald-600" />
            <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">最终答案</span>
          </div>
          <p className="text-sm whitespace-pre-wrap break-all">
            {finalAnswerText}
          </p>
          {result.citations.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              <span className="text-xs text-muted-foreground">引用:</span>
              {result.citations.map((c, i) => (
                <Badge key={i} variant="outline" className="text-[10px] font-mono">{c}</Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 判断步骤是否有可展开详情
function hasStepDetail(step: UnifiedDebugStep): boolean {
  const r = step.result
  if (step.node === 'query_router') return false
  if (step.node === 'retrieval_agent' || step.node === 'lightrag_agent') {
    return Array.isArray(r.documents) && r.documents.length > 0
  }
  if (step.node === 'sql_agent') {
    return !!(r.sql_query || (Array.isArray(r.sql_recalled_sheets) && r.sql_recalled_sheets.length > 0) || (Array.isArray(r.sql_result_rows) && r.sql_result_rows.length > 0))
  }
  if (step.node === 'answer_generator') {
    return !!(r.answer || r.final_answer)
  }
  if (step.node === 'chitchat') {
    return !!r.answer
  }
  if (step.node === 'graph_agent') {
    return !!(r.graph_context || (Array.isArray(r.graph_entities) && r.graph_entities.length > 0))
  }
  return false
}

// 步骤摘要（始终展示的单行关键信息）
function StepSummary({ step }: { step: UnifiedDebugStep }): ReactNode {
  const r = step.result
  if (step.node === 'query_router') {
    return (
      <div className="text-xs text-muted-foreground mt-0.5">
        query_type: <span className="font-mono text-foreground">{String(r.query_type ?? '')}</span>
        {r.confidence != null && <> · confidence: <span className="font-mono text-foreground">{Number(r.confidence).toFixed(3)}</span></>}
        {r.graph_eligible === true && <Badge variant="outline" className="text-[10px] ml-1">graph_eligible</Badge>}
      </div>
    )
  }
  if (step.node === 'retrieval_agent' || step.node === 'lightrag_agent') {
    const count = Number(r.count ?? 0)
    const hasExcel = r.has_excel_sheet === true
    const path = typeof r.retrieval_path === 'string' ? r.retrieval_path : ''
    return (
      <div className="text-xs text-muted-foreground mt-0.5">
        召回 <span className="font-mono font-semibold text-foreground">{count}</span> 条
        {path ? <> · path: <span className="font-mono text-foreground">{path}</span></> : null}
        {hasExcel && <Badge variant="outline" className="text-[10px] ml-1 bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border-indigo-300">含 excel_sheet</Badge>}
      </div>
    )
  }
  if (step.node === 'sql_agent') {
    const rowCount = Number(r.sql_result_row_count ?? 0)
    const sheetName = r.sql_sheet_name ? String(r.sql_sheet_name) : ''
    const hasSql = !!r.sql_query
    const err = r.sql_error ? String(r.sql_error) : ''
    const fallback = r.sql_fallback_reason ? String(r.sql_fallback_reason) : ''
    return (
      <div className="text-xs text-muted-foreground mt-0.5">
        {hasSql ? (
          <>
            {sheetName && <>sheet: <span className="font-mono text-foreground">{sheetName}</span> · </>}
            结果 <span className={`font-mono font-semibold ${rowCount === 0 ? 'text-red-500' : 'text-foreground'}`}>{rowCount}</span> 行
          </>
        ) : (
          <span className="text-red-500">未生成 SQL</span>
        )}
        {err && <span className="text-red-400 ml-1">— {err}</span>}
        {fallback && <span className="text-red-400 ml-1">— {fallback}</span>}
      </div>
    )
  }
  if (step.node === 'answer_generator') {
    const iter = r.iteration != null ? Number(r.iteration) : null
    const isIntermediate = step.intermediate
    return (
      <div className="text-xs text-muted-foreground mt-0.5">
        {iter != null && <>iteration: <span className="font-mono text-foreground">{iter}</span></>}
        {isIntermediate && <span className="text-amber-600 ml-1">· 信息不足中间态</span>}
        {r.rerouted_to_sql === true && <span className="text-amber-600 ml-1">· 将触发 SQL Tool Call</span>}
      </div>
    )
  }
  if (step.node === 'chitchat') {
    return <div className="text-xs text-muted-foreground mt-0.5">直接 LLM 回答（无检索）</div>
  }
  if (step.node === 'graph_agent') {
    const entities = Array.isArray(r.graph_entities) ? r.graph_entities.length : 0
    return (
      <div className="text-xs text-muted-foreground mt-0.5">
        实体: <span className="font-mono text-foreground">{entities}</span>
      </div>
    )
  }
  return null
}

// 步骤详情（展开后内容）
function StepDetail({ step, expandedDocs, onToggleDoc }: {
  step: UnifiedDebugStep
  expandedDocs: Record<string, boolean>
  onToggleDoc: (key: string) => void
}): ReactNode {
  const r = step.result

  if (step.node === 'retrieval_agent' || step.node === 'lightrag_agent') {
    const docs = Array.isArray(r.documents) ? r.documents as Array<Record<string, unknown>> : []
    return (
      <div className="mt-2 space-y-1">
        <div className="text-xs font-medium text-muted-foreground">召回文档 (前 {Math.min(docs.length, 10)} 条)</div>
        {docs.slice(0, 10).map((d, i) => {
          const chunkId = String(d.chunk_id ?? '')
          const filename = String(d.filename ?? d.doc_id ?? '')
          const score = d.score != null ? Number(d.score) : null
          const text = String((d.text ?? d.text_preview ?? '') as string).slice(0, 300)
          const docKey = `${step.node}-${i}`
          const meta = d.metadata as Record<string, unknown> | undefined
          const source = meta?.source ? String(meta.source) : ''
          return (
            <div key={i} className="rounded border border-border bg-muted/20 p-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                <span className="text-xs font-medium">{filename}</span>
                {source && <Badge variant="outline" className="text-[10px]">{source}</Badge>}
                {score != null && <span className="ml-auto font-mono text-xs shrink-0">score: {score.toFixed(4)}</span>}
              </div>
              <div className="text-xs text-muted-foreground font-mono truncate" title={chunkId}>{chunkId}</div>
              {text && (
                <>
                  <button onClick={() => onToggleDoc(docKey)} className="text-xs text-primary/70 hover:text-primary">
                    {expandedDocs[docKey] ? '收起' : '展开'}文本
                  </button>
                  {expandedDocs[docKey] && (
                    <p className="mt-0.5 text-xs text-muted-foreground whitespace-pre-wrap break-all">{text}</p>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  if (step.node === 'sql_agent') {
    const sql = r.sql_query ? String(r.sql_query) : ''
    const cols = Array.isArray(r.sql_result_columns) ? r.sql_result_columns as string[] : []
    const rows = Array.isArray(r.sql_result_rows) ? r.sql_result_rows as unknown[][] : []
    const recalled = Array.isArray(r.sql_recalled_sheets) ? r.sql_recalled_sheets as Array<Record<string, unknown>> : []
    const attempts = Array.isArray(r.sql_attempts) ? r.sql_attempts as Array<Record<string, unknown>> : []

    return (
      <div className="mt-2 space-y-2">
        {/* 召回 Sheet 列表 */}
        {recalled.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">召回 Sheet ({recalled.length})</div>
            <div className="space-y-0.5">
              {recalled.slice(0, 10).map((s, i) => {
                const sm = (s.sheet_meta ?? s) as Record<string, unknown>
                const sheetName = String(sm.sheet_name ?? '')
                const score = s.score != null ? Number(s.score) : 0
                const selected = s.selected === true
                return (
                  <div key={i} className="text-xs flex items-center gap-1.5">
                    <span className="font-mono">#{i + 1}</span>
                    <span className="font-mono">{sheetName}</span>
                    <Badge variant="secondary" className="text-[10px] font-mono">{score.toFixed(3)}</Badge>
                    {selected && <Badge variant="default" className="text-[10px]">已选</Badge>}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* SQL 语句 */}
        {sql && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">执行的 SQL</div>
            <pre className="text-xs font-mono p-2 bg-muted/30 rounded whitespace-pre-wrap break-all">{sql}</pre>
          </div>
        )}

        {/* 结果预览（前 5 行） */}
        {sql && rows.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">
              结果预览 (前 {Math.min(rows.length, 5)} 行 / 共 {Number(r.sql_result_row_count ?? rows.length)} 行)
            </div>
            <div className="overflow-x-auto border rounded">
              <table className="w-full text-xs">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-2 py-1 text-left font-mono">#</th>
                    {cols.map((c, i) => (
                      <th key={i} className="px-2 py-1 text-left font-mono">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 5).map((row, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-2 py-1 text-muted-foreground font-mono">{i + 1}</td>
                      {Array.isArray(row) ? row.map((cell, j) => (
                        <td key={j} className="px-2 py-1 font-mono">{String(cell ?? '')}</td>
                      )) : <td className="px-2 py-1">{String(row ?? '')}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {sql && rows.length === 0 && (
          <div className="text-xs text-muted-foreground">(空结果)</div>
        )}

        {/* 重试历史 */}
        {attempts.length > 1 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">重试历史 ({attempts.length} 次)</div>
            <div className="space-y-0.5">
              {attempts.map((a, i) => (
                <div key={i} className="text-xs">
                  <span className="font-mono">第 {String(a.attempt ?? i + 1)} 次:</span>
                  {a.error ? <span className="text-destructive ml-1">{String(a.error)}</span> : <span className="text-green-600 ml-1">成功 (rows={String(a.row_count ?? 0)})</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  if (step.node === 'answer_generator' || step.node === 'chitchat') {
    const answer = String(r.final_answer || r.answer || '')
    const citations = Array.isArray(r.citations) ? r.citations as string[] : []
    return (
      <div className="mt-2 space-y-1">
        {answer && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">
              {step.intermediate ? '中间态答案（信息不足）' : '答案'}
            </div>
            <p className="text-xs whitespace-pre-wrap break-all bg-muted/20 rounded p-2">{answer}</p>
          </div>
        )}
        {citations.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <span className="text-xs text-muted-foreground">引用:</span>
            {citations.map((c, i) => (
              <Badge key={i} variant="outline" className="text-[10px] font-mono">{c}</Badge>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (step.node === 'graph_agent') {
    const ctx = r.graph_context ? String(r.graph_context) : ''
    const entities = Array.isArray(r.graph_entities) ? r.graph_entities as string[] : []
    return (
      <div className="mt-2 space-y-1">
        {entities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <span className="text-xs text-muted-foreground">实体:</span>
            {entities.slice(0, 20).map((e, i) => (
              <Badge key={i} variant="outline" className="text-[10px]">{e}</Badge>
            ))}
          </div>
        )}
        {ctx && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">graph_context (前 500 字)</div>
            <p className="text-xs whitespace-pre-wrap break-all bg-muted/20 rounded p-2">{ctx.slice(0, 500)}</p>
          </div>
        )}
      </div>
    )
  }

  return null
}

function SqlDebugView({ sqlDebug }: { sqlDebug: import('@/lib/api').SqlDebug }) {
  const [expandedSheet, setExpandedSheet] = useState<string | null>(null)
  const [showSchema, setShowSchema] = useState(false)
  const sel = sqlDebug.selected_sheet
  const cols = sqlDebug.sql_result_columns
  const rows = sqlDebug.sql_result_rows
  const err = sqlDebug.error

  return (
    <div className="space-y-3 text-sm">
      {/* 检索路径标识 */}
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline" className="text-xs bg-violet-50 dark:bg-violet-950/30 text-violet-700 dark:text-violet-300 border-violet-300">
          NL2SQL 检索路径
        </Badge>
        {sel ? (
          <span className="text-xs text-muted-foreground">
            命中 Sheet: <span className="font-mono text-foreground">{sel.sheet_name}</span> · score={sel.score.toFixed(3)}
          </span>
        ) : (
          <span className="text-xs text-destructive">未命中 Sheet（fallback）</span>
        )}
        {err && <span className="text-xs text-destructive">错误: {err}</span>}
      </div>

      {/* 召回 Sheet 列表（每个 Sheet 含可展开的摘要作为 chunk 内容；
          selected_sheet 与 recalled 中 selected=true 的条目是同一个，不再重复展示） */}
      <div className="border rounded">
        <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">
          召回 Sheet ({sqlDebug.recalled_sheets.length})
        </div>
        {sqlDebug.recalled_sheets.length === 0 ? (
          <p className="text-xs text-muted-foreground p-2">无召回（库中无 Excel 或主题不匹配）</p>
        ) : (
          <div className="divide-y">
            {sqlDebug.recalled_sheets.map((s, i) => {
              const isExpanded = expandedSheet === s.meta_id
              const hasSummary = !!s.summary
              const toggle = () => {
                if (!hasSummary) return
                setExpandedSheet(isExpanded ? null : s.meta_id)
              }
              return (
                <div
                  key={s.meta_id || i}
                  className={`p-2 ${hasSummary ? 'cursor-pointer hover:bg-muted/40 transition-colors' : ''}`}
                  onClick={toggle}
                >
                  <div className="flex items-center gap-2">
                    {hasSummary ? (
                      <span className="text-muted-foreground shrink-0" title={isExpanded ? '收起摘要' : '展开完整摘要'}>
                        {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      </span>
                    ) : (
                      <span className="w-3 shrink-0" />
                    )}
                    <span className="text-xs font-mono">#{i + 1}</span>
                    <span className="text-xs font-mono">{s.sheet_name}</span>
                    <Badge variant="secondary" className="text-[10px] font-mono">{s.score.toFixed(3)}</Badge>
                    {s.selected && <Badge variant="default" className="text-[10px]">已选</Badge>}
                  </div>
                  {/* 默认展示摘要前 1 行，点击整行切换展开/折叠完整内容 */}
                  {s.summary && (
                    <p className={`text-xs text-muted-foreground mt-1 pl-5 ${isExpanded ? 'whitespace-pre-wrap break-all' : 'line-clamp-1'}`}>
                      {s.summary}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 选中的表结构（默认折叠，避免占用过多空间；summary 已在召回列表中展示，不重复） */}
      {sel && sel.columns.length > 0 && (
        <div className="border rounded">
          <button
            onClick={() => setShowSchema(!showSchema)}
            className="w-full px-2 py-1.5 text-xs font-medium border-b bg-muted/30 flex items-center gap-2 hover:bg-muted/50 transition-colors"
          >
            {showSchema ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <span>表结构 ({sel.columns.length} 列, {sel.row_count} 行)</span>
          </button>
          {showSchema && (
            <div className="p-2 space-y-1">
              {sel.columns.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="font-mono text-foreground">{c.column_name}</span>
                  <span className="text-muted-foreground">({c.data_type})</span>
                  {c.display_name && <span className="text-muted-foreground">→ {c.display_name}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 生成的 SQL */}
      {sqlDebug.sql && (
        <div className="border rounded">
          <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30 flex items-center gap-2">
            <span>执行的 SQL</span>
            {sqlDebug.attempts.length > 1 && (
              <Badge variant="outline" className="text-[10px]">重试 {sqlDebug.attempts.length} 次</Badge>
            )}
          </div>
          <pre className="text-xs font-mono p-2 overflow-x-auto whitespace-pre-wrap break-all bg-muted/20">
            {sqlDebug.sql}
          </pre>
        </div>
      )}

      {/* 重试历史 */}
      {sqlDebug.attempts.length > 1 && (
        <div className="border rounded">
          <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">重试历史</div>
          <div className="p-2 space-y-1">
            {sqlDebug.attempts.map((a, i) => (
              <div key={i} className="text-xs">
                <span className="font-mono">第 {a.attempt} 次:</span>
                {a.error ? <span className="text-destructive ml-1">{a.error}</span> : <span className="text-green-600 ml-1">成功 (row_count={a.row_count ?? 0})</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 执行结果（前 5 行预览，与全局约定一致） */}
      {sqlDebug.sql && (
        <div className="border rounded">
          <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">
            执行结果 (前 {Math.min(rows.length, 5)} / {sqlDebug.sql_result_row_count} 行)
          </div>
          {rows.length === 0 ? (
            <p className="text-xs text-muted-foreground p-2 italic">(空结果)</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-2 py-1 text-left font-mono">#</th>
                    {cols.map((c, i) => (
                      <th key={i} className="px-2 py-1 text-left font-mono">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 5).map((row, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-2 py-1 text-muted-foreground font-mono">{i + 1}</td>
                      {Array.isArray(row) ? row.map((cell, j) => (
                        <td key={j} className="px-2 py-1 font-mono">{String(cell ?? '')}</td>
                      )) : <td className="px-2 py-1">{String(row ?? '')}</td>}
                    </tr>
                  ))}
                  {sqlDebug.sql_result_row_count > rows.length && (
                    <tr><td colSpan={cols.length + 1} className="border-t px-2 py-1 text-muted-foreground italic">… 共 {sqlDebug.sql_result_row_count} 行，查看完整结果请展开「查询结果详情」</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* SQL 生成失败提示 */}
      {!sqlDebug.sql && err && (
        <div className="border border-destructive/30 rounded p-2 text-xs text-destructive">
          SQL 生成失败: {err}
        </div>
      )}
    </div>
  )
}

function StageMini({
  label, items, scoreField, expandedPreviews, onTogglePreview, prefix, scoreThreshold, showAll
}: {
  label: string
  items: Array<{ doc_id: string; chunk_id: string; filename: string; text_preview: string; score?: number }>
  scoreField: string
  expandedPreviews: Record<string, boolean>
  onTogglePreview: (key: string) => void
  prefix: string
  scoreThreshold?: number
  showAll?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      {label ? (
        <button
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground mb-1"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {label}
        </button>
      ) : null}
      {(open || !label) && (
        <div className="space-y-0.5">
          {items.map((c, i) => {
            const s = (c as Record<string, unknown>)[scoreField] as number
            const pass = scoreThreshold != null ? s >= scoreThreshold : null
            if (!showAll && pass === false) return null
            return (
            <div key={i} className={`rounded p-1.5 ${scoreThreshold != null ? (pass ? 'bg-green-50 dark:bg-green-950/10 border border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-950/10 border border-red-200 dark:border-red-800') : 'bg-muted/20'}`}>
              <div className="flex items-center gap-1">
                <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                <span className="text-xs break-all" title={`${c.filename || c.doc_id} / ${c.chunk_id}`}>
                  <span className="font-medium">{c.filename || c.doc_id}</span>
                  <span className="text-muted-foreground ml-1 font-mono">/ {c.chunk_id}</span>
                </span>
                <span className="ml-auto font-mono text-xs shrink-0">{s}</span>
                {pass !== null && (
                  pass ? <Check className="h-3 w-3 text-green-500 shrink-0" /> : <X className="h-3 w-3 text-red-400 shrink-0" />
                )}
              </div>
              <button onClick={() => onTogglePreview(`${prefix}-${i}`)} className="text-xs text-primary/70 hover:text-primary">
                {expandedPreviews[`${prefix}-${i}`] ? '收起' : '展开'}文本
              </button>
              {expandedPreviews[`${prefix}-${i}`] && (
                <p className="mt-0.5 text-xs text-muted-foreground whitespace-pre-wrap break-all overflow-y-auto">{c.text_preview}</p>
              )}
            </div>
          )})}
        </div>
      )}
    </div>
  )
}
