import { useState, useCallback } from 'react'
import { Upload, Search, Loader2, ChevronDown, ChevronRight, Check, X, BeakerIcon } from 'lucide-react'
import { UploadPanel } from '@/components/UploadPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { searchDebug, type SearchDebugResponse } from '@/lib/api'

export function DocumentsPage() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [showUpload, setShowUpload] = useState(false)
  const [showSearchDebug, setShowSearchDebug] = useState(false)

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    )
  }, [])

  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  const handleFolderChanged = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-[calc(100vh-3rem)]">
        <div className="lg:col-span-2 space-y-4 overflow-y-auto">
          <FolderTree
            selectedFolder={selectedFolder}
            onSelect={setSelectedFolder}
            onChanged={handleFolderChanged}
          />
          <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
        </div>

        <div className="lg:col-span-10 space-y-4 overflow-y-auto">
          <div className="flex gap-2 flex-wrap">
            <Button size="lg" onClick={() => setShowUpload(true)}>
              <Upload className="h-5 w-5 mr-2" />
              上传文档
            </Button>
            <Button
              variant={showSearchDebug ? 'default' : 'outline'}
              size="lg"
              onClick={() => setShowSearchDebug(!showSearchDebug)}
            >
              <BeakerIcon className="h-5 w-5 mr-2" />
              检索测试
            </Button>
          </div>
          {showSearchDebug && (
            <SearchDebugPanel folder={selectedFolder} tags={selectedTags} />
          )}
          <DocumentList folder={selectedFolder} tags={selectedTags} key={refreshKey} />
        </div>

        <UploadPanel
          folder={selectedFolder}
          open={showUpload}
          onOpenChange={setShowUpload}
          onUploadComplete={handleUploadComplete}
        />
      </div>
    </div>
  )
}

function SearchDebugPanel({ folder, tags }: { folder: string | null; tags: string[] }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchDebugResponse | null>(null)
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})
  const [expandedPreviews, setExpandedPreviews] = useState<Record<string, boolean>>({})

  const togglePreview = (key: string) => {
    setExpandedPreviews(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSearch = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setResult(null)
    setExpandedSections({})
    setExpandedPreviews({})
    try {
      const res = await searchDebug(query.trim(), folder, tags)
      setResult(res)
      if (res.stages.rrf.length > 0) setExpandedSections({ rrf: true, rerank: true })
    } catch (err) {
      console.error('Search debug failed:', err)
    } finally {
      setLoading(false)
    }
  }

  const filterInfo = []
  if (folder) filterInfo.push(`文件夹: ${folder}`)
  if (tags.length) filterInfo.push(`标签: ${tags.join(', ')}`)

  return (
    <Card className="p-4 text-sm">
      <div className="flex items-center gap-2 mb-3">
        <Search className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">检索测试</span>
        <span className="text-xs text-muted-foreground">查看每个阶段的召回情况和阈值过滤效果</span>
        {filterInfo.length > 0 && (
          <div className="flex gap-1 ml-auto">
            {filterInfo.map((f, i) => (
              <Badge key={i} variant="secondary" className="text-xs">{f}</Badge>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-2">
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
        <div className="mt-4 space-y-3">
          {/* Summary bar */}
          <div className="flex items-center gap-3 text-sm bg-muted/30 rounded p-2">
            <span className="text-muted-foreground">阈值:</span>
            <span className="font-mono font-semibold">{result.threshold}</span>
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
            {result.final_count === 0 && (
              <span className="text-xs text-red-400">— 所有结果被阈值过滤！尝试降低阈值</span>
            )}
            {result.filtered_out_by_rerank_threshold > 0 && (
              <span className="text-xs text-red-400 ml-auto">
                Rerank 阶段过滤 {result.filtered_out_by_rerank_threshold} 条
              </span>
            )}
          </div>

          {/* Stage tabs */}
          <div className="grid grid-cols-2 gap-3">
            {/* RRF Stage */}
            <div>
              <button
                onClick={() => setExpandedSections(s => ({ ...s, rrf: !s.rrf }))}
                className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground mb-2"
              >
                {expandedSections['rrf'] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                RRF 融合结果 ({result.stages.rrf.length} 条)
              </button>
              {expandedSections['rrf'] && (
                <div className="space-y-1 max-h-96 overflow-y-auto">
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
            </div>

            {/* Rerank Stage */}
            <div>
              <button
                onClick={() => setExpandedSections(s => ({ ...s, rerank: !s.rerank }))}
                className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground mb-2"
              >
                {expandedSections['rerank'] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                Reranker 重排序 ({result.stages.rerank.length} 条)
              </button>
              {expandedSections['rerank'] && (
                <div className="space-y-1 max-h-96 overflow-y-auto">
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
            </div>
          </div>

          {/* Dense / BM25 top5 previews */}
          <div className="grid grid-cols-2 gap-3">
            <StageMini label={`Dense 向量 Top ${result.stages.dense_top5.length}`} items={result.stages.dense_top5} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="dense" />
            <StageMini label={`BM25 关键词 Top ${result.stages.bm25_top5.length}`} items={result.stages.bm25_top5} scoreField="score" expandedPreviews={expandedPreviews} onTogglePreview={togglePreview} prefix="bm25" />
          </div>
        </div>
      )}
    </Card>
  )
}

function StageMini({
  label, items, scoreField, expandedPreviews, onTogglePreview, prefix
}: {
  label: string
  items: Array<{ doc_id: string; filename: string; text_preview: string; score?: number }>
  scoreField: string
  expandedPreviews: Record<string, boolean>
  onTogglePreview: (key: string) => void
  prefix: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground mb-1"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {label}
      </button>
      {open && (
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {items.map((c, i) => (
            <div key={i} className="bg-muted/20 rounded p-1.5">
              <div className="flex items-center gap-1">
                <span className="text-primary font-semibold text-xs">[{i + 1}]</span>
                <span className="text-xs truncate max-w-[150px]" title={c.filename || c.doc_id}>{c.filename || c.doc_id}</span>
                <span className="ml-auto font-mono text-xs">{(c as Record<string, unknown>)[scoreField] as number}</span>
              </div>
              <button onClick={() => onTogglePreview(`${prefix}-${i}`)} className="text-xs text-primary/70 hover:text-primary">
                {expandedPreviews[`${prefix}-${i}`] ? '收起' : '展开'}文本
              </button>
              {expandedPreviews[`${prefix}-${i}`] && (
                <p className="mt-0.5 text-xs text-muted-foreground whitespace-pre-wrap break-all max-h-20 overflow-y-auto">{c.text_preview}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
