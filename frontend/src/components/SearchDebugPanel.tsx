import { useState } from 'react'
import { Search, Loader2, ChevronDown, ChevronRight, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { searchDebug, updateConfigOverride, type SearchDebugResponse } from '@/lib/api'

export function SearchDebugPanel({ folder, docId, tags, folderTree, tagFilter }: {
  folder: string | null; docId: string | null; tags: string[]
  folderTree: React.ReactNode; tagFilter: React.ReactNode
}) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchDebugResponse | null>(null)
  const [expandedPreviews, setExpandedPreviews] = useState<Record<string, boolean>>({})
  const [resultTab, setResultTab] = useState<string>('rewrite')
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)

  const togglePreview = (key: string) => {
    setExpandedPreviews(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSearch = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setResult(null)
    setExpandedPreviews({})
    setResultTab('rewrite')
    try {
      const res = await searchDebug(query.trim(), folder, tags, docId)
      setResult(res)
    } catch (err) {
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

  const ThresholdValue = ({ label, configKey, value }: { label: string; configKey: string; value: number }) => (
    <>
      <span className="text-muted-foreground">{label}:</span>
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
          <div className="flex gap-2 flex-none">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
              placeholder="输入查询文本，测试检索召回效果..."
              className="flex-1"
            />
            <Button onClick={handleSearch} disabled={loading || !query.trim()}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Search className="h-4 w-4 mr-1" />}
              检索
            </Button>
          </div>

          {result && (
            <div className="mt-3 flex-1 min-h-0 overflow-y-auto space-y-3">
              <div className="flex items-center gap-3 text-sm bg-muted/30 rounded p-2 flex-wrap flex-none">
                <ThresholdValue label="Dense 阈值" configKey="dense_vector_threshold" value={result.dense_threshold || result.threshold} />
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="RRF 阈值" configKey="retrieval_similarity_threshold" value={result.threshold} />
                <span className="text-muted-foreground">|</span>
                <ThresholdValue label="Rerank 阈值" configKey="reranker_score_threshold" value={result.rerank_threshold || 0} />
                <span className="text-muted-foreground">|</span>
                <span className="text-muted-foreground">RRF 候选:</span>
                <span className="font-mono">{result.stages.rrf.length}</span>
                <span className="text-muted-foreground">|</span>
                <span className="text-muted-foreground">Rerank:</span>
                <span className="font-mono">{result.stages.rerank.length}</span>
                <span className="text-muted-foreground">|</span>
                <span className="text-muted-foreground">最终输出:</span>
                <span className={`font-mono font-semibold ${result.final_count === 0 ? 'text-red-500' : 'text-primary'}`}>
                  {result.final_count}
                </span>
                {editingKey && saving && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                {result.final_count === 0 && (
                  <span className="text-xs text-red-400">— 所有结果被阈值过滤！点击阈值数值修改</span>
                )}
                {result.filtered_out_by_rerank_threshold > 0 && (
                  <span className="text-xs text-red-400 ml-auto">
                    Rerank 阶段过滤 {result.filtered_out_by_rerank_threshold} 条
                  </span>
                )}
              </div>

              <div className="flex-1 min-h-0 flex flex-col">
                <div className="flex gap-0 border-b flex-none">
                  {[
                    { key: 'rewrite', label: '查询改写' },
                    { key: 'rrf', label: `RRF融合 (${result.stages.rrf.length})` },
                    { key: 'rerank', label: `Reranker (${result.stages.rerank.length})` },
                    { key: 'dense', label: `Dense向量 Top ${result.stages.dense_top5.length}` },
                    { key: 'bm25', label: `BM25 Top ${result.stages.bm25_top5.length}` },
                  ].map(t => (
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
                          <div className="bg-muted/30 rounded p-3 space-y-1">
                            <div className="text-xs font-medium text-muted-foreground mb-2">原始查询</div>
                            <pre className="text-sm whitespace-pre-wrap break-all">{result.rewrite.original}</pre>
                            {result.rewrite.query_tokens.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1">
                                {result.rewrite.query_tokens.map((t, i) => (
                                  <Badge key={i} variant="outline" className="text-xs font-mono">{t}</Badge>
                                ))}
                              </div>
                            )}
                          </div>
                          <div className="bg-blue-50 dark:bg-blue-950/20 rounded p-3 space-y-1">
                            <div className="text-xs font-medium text-blue-600 dark:text-blue-400 mb-2">Dense 查询（语义检索用）</div>
                            <pre className="text-sm whitespace-pre-wrap break-all">{result.rewrite.dense_query}</pre>
                            <div className="flex flex-wrap gap-1 mt-1">
                              {result.rewrite.dense_tokens.map((t, i) => (
                                <Badge key={i} variant="outline" className="text-xs font-mono bg-blue-50 dark:bg-blue-950/30">{t}</Badge>
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
                      ) : (
                        <div className="text-sm text-muted-foreground text-center py-8">
                          查询改写已禁用（query_rewrite_enabled = false）
                        </div>
                      )}
                    </div>
                  )}
                  {resultTab === 'rrf' && (
                    <div className="space-y-1">
                      {result.stages.rrf.map((c, i) => (
                        <div key={i} className={`rounded p-2 border ${c.rrf_pass_threshold ? 'bg-muted/20 border-border' : 'bg-red-50 dark:bg-red-950/10 border-red-200 dark:border-red-800'}`}>
                          <div className="flex items-center gap-1.5">
                            <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                            <span className="text-xs truncate max-w-[200px]" title={c.filename || c.doc_id}>{c.filename || c.doc_id}</span>
                            <span className="ml-auto font-mono text-xs">RRF: {c.rrf_normalized}</span>
                            {c.rrf_pass_threshold ? (
                              <Check className="h-3 w-3 text-green-500" />
                            ) : (
                              <X className="h-3 w-3 text-red-400" />
                            )}
                          </div>
                          <div className="flex gap-3 mt-0.5 text-xs text-muted-foreground/50 font-mono">
                            <span>Dense: {c.dense_score?.toFixed(4) || '-'}</span>
                            <span>BM25: {c.bm25_score?.toFixed(4) || '-'}</span>
                          </div>
                          <button onClick={() => togglePreview(`rrf-${i}`)} className="text-xs text-primary/70 hover:text-primary mt-0.5">
                            {expandedPreviews[`rrf-${i}`] ? '收起' : '展开'}文本
                          </button>
                          {expandedPreviews[`rrf-${i}`] && (
                            <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-all max-h-24 overflow-y-auto">{c.text_preview}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {resultTab === 'rerank' && (
                    <div className="space-y-1">
                      {result.stages.rerank.map((c, i) => (
                        <div key={i} className={`rounded p-2 border ${c.rerank_pass_threshold ? 'bg-muted/20 border-border' : 'bg-red-50 dark:bg-red-950/10 border-red-200 dark:border-red-800'}`}>
                          <div className="flex items-center gap-1.5">
                            <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                            <span className="text-xs truncate max-w-[200px]" title={c.filename || c.doc_id}>{c.filename || c.doc_id}</span>
                            <span className="ml-auto font-mono text-xs">score: {c.rerank_score}</span>
                            {c.rerank_pass_threshold ? (
                              <Check className="h-3 w-3 text-green-500" />
                            ) : (
                              <X className="h-3 w-3 text-red-400" />
                            )}
                          </div>
                          <button onClick={() => togglePreview(`rerank-${i}`)} className="text-xs text-primary/70 hover:text-primary mt-0.5">
                            {expandedPreviews[`rerank-${i}`] ? '收起' : '展开'}文本
                          </button>
                          {expandedPreviews[`rerank-${i}`] && (
                            <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-all max-h-24 overflow-y-auto">{c.text_preview}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {resultTab === 'dense' && (
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">
                        阈值 {result.dense_threshold || result.threshold} 通过 {denseUpToThreshold}/{result.stages.dense_top5.length}
                      </span>
                      <StageMini label="" items={result.stages.dense_top5.map(c => ({ ...c, score: c.score ?? 0 }))} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="dense" scoreThreshold={result.dense_threshold || result.threshold} />
                    </div>
                  )}
                  {resultTab === 'bm25' && (
                    <StageMini label="" items={result.stages.bm25_top5} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="bm25" />
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

function StageMini({
  label, items, scoreField, expandedPreviews, onTogglePreview, prefix, scoreThreshold
}: {
  label: string
  items: Array<{ doc_id: string; filename: string; text_preview: string; score?: number }>
  scoreField: string
  expandedPreviews: Record<string, boolean>
  onTogglePreview: (key: string) => void
  prefix: string
  scoreThreshold?: number
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
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {items.map((c, i) => {
            const s = (c as Record<string, unknown>)[scoreField] as number
            const pass = scoreThreshold != null ? s >= scoreThreshold : null
            return (
            <div key={i} className={`rounded p-1.5 ${scoreThreshold != null ? (pass ? 'bg-green-50 dark:bg-green-950/10 border border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-950/10 border border-red-200 dark:border-red-800') : 'bg-muted/20'}`}>
              <div className="flex items-center gap-1">
                <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                <span className="text-xs truncate max-w-[150px]" title={c.filename || c.doc_id}>{c.filename || c.doc_id}</span>
                <span className="ml-auto font-mono text-xs">{s}</span>
                {pass !== null && (
                  pass ? <Check className="h-3 w-3 text-green-500" /> : <X className="h-3 w-3 text-red-400" />
                )}
              </div>
              <button onClick={() => onTogglePreview(`${prefix}-${i}`)} className="text-xs text-primary/70 hover:text-primary">
                {expandedPreviews[`${prefix}-${i}`] ? '收起' : '展开'}文本
              </button>
              {expandedPreviews[`${prefix}-${i}`] && (
                <p className="mt-0.5 text-xs text-muted-foreground whitespace-pre-wrap break-all max-h-20 overflow-y-auto">{c.text_preview}</p>
              )}
            </div>
          )})}
        </div>
      )}
    </div>
  )
}
