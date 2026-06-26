import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Loader2, ChevronDown, ChevronRight, Check, X, Eye, EyeOff, HelpCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { searchDebug, updateConfigOverride, type SearchDebugResponse } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

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
  const [result, setResult] = useState<SearchDebugResponse | null>(null)
  const [error, setError] = useState('')
  const [expandedPreviews, setExpandedPreviews] = useState<Record<string, boolean>>({})
  const [resultTab, setResultTab] = useState<string>('rewrite')
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [showAll, setShowAll] = useState(true)
  const [queryFilter, setQueryFilter] = useState<number>(-1) // -1=汇总, 0..N-1=按改写 query 筛选
  const [forcePath, setForcePath] = useState<'auto' | 'doc' | 'sql'>('auto')
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
      // 切到 SQL 路径时重置 tab
      if (res.query_type === 'sql_query') {
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
  const denseUpToThreshold = result?.stages?.dense_top5 ? result.stages.dense_top5.filter(c => (c.score ?? 0) >= (result.dense_threshold || result.threshold)).length : 0
  // Dense 召回去重并集 chunk 数：multi 模式用后端计算的 dense_union_count（所有 Q 完整召回去重）；
  // 单 query 模式取 dense_top5.length
  const denseUnionCount = result?.multi_query
    ? (result.dense_union_count ?? 0)
    : (result?.stages?.dense_top5?.length ?? 0)

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
              onChange={(e) => setForcePath(e.target.value as 'auto' | 'doc' | 'sql')}
              className="text-xs border rounded px-1.5 py-1 bg-background"
              title="强制检索路径：auto=按 query_type 自动判断；doc=文本 RAG；sql=NL2SQL"
            >
              <option value="auto">自动</option>
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

          {result && (
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

              {/* 第二行：检索流程对照（配置值 → 实际产出条数） */}
              <div className="flex items-center gap-2 text-xs flex-none px-1 flex-wrap">
                <span className="text-muted-foreground font-medium">流程对照:</span>

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

function SqlDebugView({ sqlDebug }: { sqlDebug: import('@/lib/api').SqlDebug }) {
  const [expandedSheet, setExpandedSheet] = useState<string | null>(null)
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

      {/* 召回 Sheet 列表 */}
      <div className="border rounded">
        <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">
          召回 Sheet ({sqlDebug.recalled_sheets.length})
        </div>
        {sqlDebug.recalled_sheets.length === 0 ? (
          <p className="text-xs text-muted-foreground p-2">无召回（库中无 Excel 或主题不匹配）</p>
        ) : (
          <div className="divide-y">
            {sqlDebug.recalled_sheets.map((s, i) => (
              <div key={s.meta_id || i} className="p-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono">#{i + 1}</span>
                  <span className="text-xs font-mono">{s.sheet_name}</span>
                  <Badge variant="secondary" className="text-[10px] font-mono">{s.score.toFixed(3)}</Badge>
                  {s.selected && <Badge variant="default" className="text-[10px]">已选</Badge>}
                  <button
                    onClick={() => setExpandedSheet(expandedSheet === s.meta_id ? null : s.meta_id)}
                    className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                  >
                    {expandedSheet === s.meta_id ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  </button>
                </div>
                {expandedSheet === s.meta_id && s.summary && (
                  <p className="text-xs text-muted-foreground mt-1 pl-6">{s.summary}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 选中的表结构 */}
      {sel && sel.columns.length > 0 && (
        <div className="border rounded">
          <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">
            表结构 ({sel.columns.length} 列, {sel.row_count} 行)
          </div>
          <div className="p-2 space-y-1">
            {sel.columns.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-foreground">{c.en}</span>
                <span className="text-muted-foreground">({c.type})</span>
                {c.cn && <span className="text-muted-foreground">→ {c.cn}</span>}
              </div>
            ))}
          </div>
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

      {/* 执行结果 */}
      {sqlDebug.sql && (
        <div className="border rounded">
          <div className="px-2 py-1.5 text-xs font-medium border-b bg-muted/30">
            执行结果 ({sqlDebug.sql_result_row_count} 行)
          </div>
          {rows.length === 0 ? (
            <p className="text-xs text-muted-foreground p-2">空结果</p>
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
                  {rows.slice(0, 50).map((row, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-2 py-1 text-muted-foreground font-mono">{i + 1}</td>
                      {Array.isArray(row) ? row.map((cell, j) => (
                        <td key={j} className="px-2 py-1 font-mono">{String(cell ?? '')}</td>
                      )) : <td className="px-2 py-1">{String(row ?? '')}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
              {sqlDebug.sql_result_row_count > 50 && (
                <p className="text-xs text-muted-foreground p-2">
                  ... 共 {sqlDebug.sql_result_row_count} 行，仅显示前 50 行
                </p>
              )}
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
