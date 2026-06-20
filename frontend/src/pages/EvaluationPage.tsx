import { useState, useEffect, useCallback, useRef } from 'react'
import {
  listDataset, addSample, updateSample, deleteSample, importDataset, exportDataset,
  runEvaluation, listResults, getResult, deleteResult, generateDataset, listFolders,
} from '@/lib/api'
import type {
  EvalSample, EvalResultSummary, EvalResultDetail, EvalSampleResult, EvalProgressEvent,
  GenerateProgressEvent, FolderInfo,
} from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Database, Play, BarChart3, History, Plus, Trash2, Edit3, Upload, Download,
  Loader2, CheckCircle2, XCircle, Clock, RefreshCw, FileText, AlertTriangle,
  Sparkles, FolderSearch,
} from 'lucide-react'

type Tab = 'dataset' | 'run' | 'results'

const QUERY_TYPES = ['simple_fact', 'definition', 'comparison', 'multi_hop', 'holistic', 'chitchat']

// ── Dataset Management ──

function DatasetTab() {
  const [samples, setSamples] = useState<EvalSample[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<EvalSample | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [filterType, setFilterType] = useState('')
  const [showGenerate, setShowGenerate] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listDataset()
      setSamples(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (id: string) => {
    try {
      await deleteSample(id)
      setSamples((prev) => prev.filter((s) => s.id !== id))
    } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Delete failed') }
  }

  const handleExport = async () => {
    try {
      const data = await exportDataset()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'dataset.json'; a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) { setError(e instanceof Error ? e.message : 'Export failed') }
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const samples = Array.isArray(data) ? data : []
      await importDataset(samples, 'replace')
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed')
    }
    e.target.value = ''
  }

  const filtered = filterType ? samples.filter((s) => s.query_type === filterType) : samples

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />{error}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus className="h-4 w-4 mr-1" />添加样本
        </Button>
        <Button size="sm" variant="outline" onClick={handleExport}>
          <Download className="h-4 w-4 mr-1" />导出 JSON
        </Button>
        <Button size="sm" variant="outline" onClick={() => setShowGenerate(true)}>
          <Sparkles className="h-4 w-4 mr-1" />从知识库生成
        </Button>
        <label className="cursor-pointer">
          <Button size="sm" variant="outline" asChild>
            <span><Upload className="h-4 w-4 mr-1" />导入 JSON</span>
          </Button>
          <input type="file" accept=".json" className="hidden" onChange={handleImportFile} />
        </label>
        <Separator orientation="vertical" className="h-6 mx-1" />
        <Badge variant="secondary">{samples.length} 条样本</Badge>
        {QUERY_TYPES.map((t) => (
          <Badge
            key={t}
            variant={filterType === t ? 'default' : 'outline'}
            className="cursor-pointer"
            onClick={() => setFilterType(filterType === t ? '' : t)}
          >
            {t}
          </Badge>
        ))}
        {filterType && (
          <Button size="sm" variant="ghost" onClick={() => setFilterType('')} className="h-6 text-xs">清除筛选</Button>
        )}
      </div>

      {/* Sample List */}
      <ScrollArea className="h-[calc(100vh-16rem)]">
        <div className="space-y-2">
          {filtered.map((s) => (
            <Card key={s.id} className="p-3 hover:bg-muted/30 transition-colors">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{s.id}</code>
                    <Badge variant="secondary" className="text-xs">{s.query_type}</Badge>
                  </div>
                  <p className="text-sm font-medium truncate">{s.query}</p>
                  {s.ground_truth_answer && (
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                      {s.ground_truth_answer}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditing(s)}>
                    <Edit3 className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(s.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
          {filtered.length === 0 && (
            <p className="text-center text-muted-foreground py-12">暂无样本</p>
          )}
        </div>
      </ScrollArea>

      {/* Add Sample Dialog */}
      <SampleFormDialog
        open={showAdd}
        onOpenChange={setShowAdd}
        onSave={async (data) => {
          await addSample(data as EvalSample)
          load()
        }}
      />

      {/* Edit Sample Dialog */}
      {editing && (
        <SampleFormDialog
          open
          existing={editing}
          onOpenChange={(open) => { if (!open) setEditing(null) }}
          onSave={async (data) => {
            await updateSample(editing.id, data)
            load()
            setEditing(null)
          }}
        />
      )}

      {/* Generate from KB Dialog */}
      <GenerateDatasetDialog
        open={showGenerate}
        onOpenChange={setShowGenerate}
        onDone={() => load()}
      />
    </div>
  )
}

function SampleFormDialog({
  open, onOpenChange, onSave, existing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (data: Partial<EvalSample>) => Promise<void>
  existing?: EvalSample
}) {
  const [form, setForm] = useState<Partial<EvalSample>>(
    existing ?? { id: '', query: '', query_type: 'simple_fact', ground_truth_answer: '', ground_truth_sources: [], ground_truth_ids: [] }
  )
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (existing) setForm(existing)
  }, [existing])

  const handleSave = async () => {
    setSaving(true)
    try { await onSave(form) }
    catch { /* handled upstream */ }
    setSaving(false)
    if (!existing) onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{existing ? '编辑样本' : '添加样本'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">ID</label>
            <Input value={form.id || ''} onChange={(e) => setForm({ ...form, id: e.target.value })} disabled={!!existing} placeholder="e.g. 001" />
          </div>
          <div>
            <label className="text-sm font-medium">查询类型</label>
            <select
              className="w-full mt-1 rounded-md border bg-background px-3 py-2 text-sm"
              value={form.query_type || 'simple_fact'}
              onChange={(e) => setForm({ ...form, query_type: e.target.value })}
            >
              {QUERY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium">查询问题</label>
            <Textarea value={form.query || ''} onChange={(e) => setForm({ ...form, query: e.target.value })} rows={2} />
          </div>
          <div>
            <label className="text-sm font-medium">参考答案</label>
            <Textarea value={form.ground_truth_answer || ''} onChange={(e) => setForm({ ...form, ground_truth_answer: e.target.value })} rows={3} />
          </div>
          <div>
            <label className="text-sm font-medium">参考文献来源 (逗号分隔)</label>
            <Input
              value={(form.ground_truth_sources || []).join(', ')}
              onChange={(e) => setForm({ ...form, ground_truth_sources: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
              placeholder="source1, source2"
            />
          </div>
          <div>
            <label className="text-sm font-medium">参考 Chunk IDs (逗号分隔)</label>
            <Input
              value={(form.ground_truth_ids || []).join(', ')}
              onChange={(e) => setForm({ ...form, ground_truth_ids: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
              placeholder="chunk_001, chunk_002"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSave} disabled={saving || !form.id || !form.query}>
            {saving ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Generate Dataset from KB Dialog ──

function GenerateDatasetDialog({
  open, onOpenChange, onDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone: () => void
}) {
  const [folder, setFolder] = useState('/')
  const [maxDocs, setMaxDocs] = useState(5)
  const [samplesPerDoc, setSamplesPerDoc] = useState(3)
  const [mode, setMode] = useState<'replace' | 'merge'>('merge')
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [doneCount, setDoneCount] = useState(0)
  const [folders, setFolders] = useState<FolderInfo[]>([])

  useEffect(() => {
    if (open) {
      listFolders().then(setFolders).catch(() => {})
      setLog([])
      setDoneCount(0)
      setRunning(false)
    }
  }, [open])

  const handleGenerate = async () => {
    setRunning(true)
    setLog([])
    try {
      await generateDataset(
        folder || '/', maxDocs, samplesPerDoc, mode,
        (evt: GenerateProgressEvent) => {
          if (evt.type === 'start') {
            setLog((prev) => [...prev, `开始生成: ${evt.total} 个文档`])
          } else if (evt.type === 'progress') {
            setLog((prev) => [...prev, `处理文档: ${evt.doc_id}`])
          } else if (evt.type === 'sample_generated') {
            setLog((prev) => [...prev, `  生成: [${evt.sample_id}] ${evt.query}`])
          }
        },
        (count) => {
          setDoneCount(count)
          setRunning(false)
          setLog((prev) => [...prev, `完成! 共生成 ${count} 条样本`])
          if (count > 0) onDone()
        },
        (err) => {
          setLog((prev) => [...prev, `错误: ${err}`])
          setRunning(false)
        },
      )
    } catch (e: unknown) {
      setLog((prev) => [...prev, `异常: ${String(e)}`])
      setRunning(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />从知识库生成数据集
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">知识库文件夹</label>
            <div className="flex gap-2 mt-1">
              <select
                className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
              >
                <option value="/">全部 (/ )</option>
                {folders.map((f) => (
                  <option key={f.folder} value={f.folder}>
                    {f.folder} ({f.doc_count} 文档)
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium">文档上限</label>
              <Input type="number" value={maxDocs} onChange={(e) => setMaxDocs(Number(e.target.value))} min={1} max={50} disabled={running} />
            </div>
            <div>
              <label className="text-sm font-medium">每文档样本数</label>
              <Input type="number" value={samplesPerDoc} onChange={(e) => setSamplesPerDoc(Number(e.target.value))} min={1} max={10} disabled={running} />
            </div>
          </div>
          <div>
            <label className="text-sm font-medium">导入模式</label>
            <div className="flex gap-2 mt-1">
              <Button size="sm" variant={mode === 'merge' ? 'default' : 'outline'} onClick={() => setMode('merge')} disabled={running}>合并</Button>
              <Button size="sm" variant={mode === 'replace' ? 'default' : 'outline'} onClick={() => setMode('replace')} disabled={running}>替换</Button>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
            <Button onClick={handleGenerate} disabled={running}>
              {running ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
              {running ? '生成中...' : '开始生成'}
            </Button>
          </div>
          {log.length > 0 && (
            <div className="p-3 rounded-md bg-muted/50 max-h-48 overflow-y-auto">
              {log.map((line, i) => (
                <pre key={i} className="text-xs text-muted-foreground whitespace-pre-wrap">{line}</pre>
              ))}
              {doneCount > 0 && (
                <p className="text-sm font-medium text-green-600 mt-2">生成完成! 共 {doneCount} 条样本已保存。</p>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── Run Evaluation ──

function RunTab() {
  const [maxSamples, setMaxSamples] = useState<number | null>(10)
  const [evalFolder, setEvalFolder] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [sampleresults, setSampleResults] = useState<{ sample_id: string; processing_time_ms: number; error?: string }[]>([])
  const [done, setDone] = useState(false)
  const [summary, setSummary] = useState<Record<string, number> | null>(null)
  const [error, setError] = useState('')
  const [lastFile, setLastFile] = useState('')
  const [folders, setFolders] = useState<FolderInfo[]>([])
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => { listFolders().then(setFolders).catch(() => {}) }, [])

  const handleRun = async () => {
    setRunning(true)
    setDone(false)
    setSummary(null)
    setError('')
    setSampleResults([])
    setProgress({ current: 0, total: 0 })

    try {
      await runEvaluation(
        maxSamples,
        evalFolder,
        (evt: EvalProgressEvent) => {
          if (evt.type === 'start') {
            setProgress({ current: 0, total: evt.total || 0 })
          } else if (evt.type === 'progress') {
            setProgress({ current: evt.current || 0, total: evt.total || 0 })
          } else if (evt.type === 'sample_done') {
            setSampleResults((prev) => [...prev, { sample_id: evt.sample_id || '', processing_time_ms: evt.processing_time_ms || 0, error: evt.error }])
          }
          if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
        },
        (sum, filename) => {
          setSummary(sum)
          setLastFile(filename)
          setDone(true)
          setRunning(false)
        },
        (err) => {
          setError(err)
          setRunning(false)
        },
      )
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Run failed')
      setRunning(false)
    }
  }

  const pct = progress.total > 0 ? (progress.current / progress.total) * 100 : 0

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />{error}
        </div>
      )}

      <Card>
        <CardContent className="py-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-sm">样本上限:</label>
              <Input
                type="number"
                className="w-24"
                value={maxSamples ?? ''}
                onChange={(e) => setMaxSamples(e.target.value ? parseInt(e.target.value) : null)}
                disabled={running}
                placeholder="全部"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm">检索范围:</label>
              <select
                className="rounded-md border bg-background px-3 py-2 text-sm max-w-[200px]"
                value={evalFolder || '/'}
                onChange={(e) => setEvalFolder(e.target.value === '/' ? null : e.target.value)}
                disabled={running}
              >
                <option value="/">全部知识库</option>
                {folders.map((f) => (
                  <option key={f.folder} value={f.folder}>
                    {f.folder} ({f.doc_count})
                  </option>
                ))}
              </select>
            </div>
            <Button onClick={handleRun} disabled={running} className="gap-1">
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {running ? '运行中...' : '开始评估'}
            </Button>
            {running && (
              <Button variant="outline" disabled className="gap-1">
                <Clock className="h-4 w-4" /> 评估中...
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Progress */}
      {(running || done) && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">评估进度</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <Progress value={done ? 100 : pct} className="flex-1" />
              <span className="text-sm text-muted-foreground shrink-0">
                {progress.current}/{progress.total}
              </span>
            </div>
            {done && <Badge variant="default" className="gap-1"><CheckCircle2 className="h-3 w-3" />完成</Badge>}
          </CardContent>
        </Card>
      )}

      {/* Summary */}
      {summary && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">评估结果摘要</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
              <MetricBox label="样本数" value={summary.num_samples?.toString() || '-'} />
              <MetricBox label="Recall@5" value={summary.recall_at_5?.toFixed(4) || '-'} />
              <MetricBox label="Recall@10" value={summary.recall_at_10?.toFixed(4) || '-'} />
              <MetricBox label="语义相似度" value={summary.semantic_similarity?.toFixed(4) || '-'} />
              <MetricBox label="Judge准确率" value={summary.judge_accuracy?.toFixed(4) || '-'} />
              <MetricBox label="引用准确率" value={summary.citation_accuracy?.toFixed(4) || '-'} />
            </div>
            {lastFile && <p className="text-xs text-muted-foreground mt-3">结果已保存: {lastFile}</p>}
          </CardContent>
        </Card>
      )}

      {/* Sample Log */}
      {sampleresults.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">样本结果 ({sampleresults.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div ref={logRef} className="max-h-64 overflow-y-auto space-y-1">
              {sampleresults.map((r, i) => (
                <div key={i} className="flex items-center gap-2 text-sm py-1 px-2 rounded hover:bg-muted/50">
                  {r.error ? <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
                    : <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />}
                  <span className="font-mono text-xs">{r.sample_id}</span>
                  <span className="text-muted-foreground text-xs ml-auto">
                    {r.processing_time_ms > 0 ? `${(r.processing_time_ms / 1000).toFixed(1)}s` : ''}
                  </span>
                  {r.error && <span className="text-xs text-destructive truncate">{r.error}</span>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 rounded-lg border text-center">
      <p className="text-xl font-bold">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  )
}

// ── Results History ──

function ResultsTab() {
  const [results, setResults] = useState<EvalResultSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<EvalResultDetail | null>(null)
  const [viewingFile, setViewingFile] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listResults()
      setResults(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const handleView = async (filename: string) => {
    setDetailLoading(true)
    setViewingFile(filename)
    try {
      const detail = await getResult(filename)
      setSelected(detail)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'View failed')
    }
    setDetailLoading(false)
  }

  const handleDelete = async (filename: string) => {
    try {
      await deleteResult(filename)
      setResults((prev) => prev.filter((r) => r.filename !== filename))
      if (selected && viewingFile === filename) {
        setSelected(null)
        setViewingFile('')
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />{error}
        </div>
      )}

      {results.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <History className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>暂无评估结果</p>
            <p className="text-xs">运行一次评估后，结果将显示在这里</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">历史结果 ({results.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea className="max-h-64">
                <div className="space-y-2">
                  {results.map((r) => (
                    <div
                      key={r.filename}
                      className={`flex items-center gap-3 p-2 rounded-lg border cursor-pointer transition-colors ${
                        viewingFile === r.filename ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'
                      }`}
                      onClick={() => handleView(r.filename)}
                    >
                      <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium font-mono">{r.filename}</p>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{r.num_samples} 样本</span>
                          <span>Recall@5: {r.recall_at_5.toFixed(3)}</span>
                          <span>Judge: {r.judge_accuracy.toFixed(3)}</span>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive shrink-0"
                        onClick={(e) => { e.stopPropagation(); handleDelete(r.filename) }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Detail View */}
          {detailLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
          ) : selected ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">结果详情: {viewingFile}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Metrics */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                  <MetricBox label="样本数" value={selected.summary.num_samples?.toString() || '-'} />
                  <MetricBox label="Recall@5" value={selected.summary.recall_at_5?.toFixed(4) || '-'} />
                  <MetricBox label="Recall@10" value={selected.summary.recall_at_10?.toFixed(4) || '-'} />
                  <MetricBox label="语义相似度" value={selected.summary.semantic_similarity?.toFixed(4) || '-'} />
                  <MetricBox label="Judge准确率" value={selected.summary.judge_accuracy?.toFixed(4) || '-'} />
                  <MetricBox label="引用准确率" value={selected.summary.citation_accuracy?.toFixed(4) || '-'} />
                </div>
                <div className="text-xs text-muted-foreground">
                  总耗时: {selected.total_time_seconds?.toFixed(1)}s | 平均每样本: {(selected.avg_time_per_sample).toFixed(1)}s
                </div>
                <Separator />
                {/* Per-sample results */}
                <ScrollArea className="max-h-96">
                  <div className="space-y-2">
                    {selected.results.map((r: EvalSampleResult, i: number) => (
                      <div key={i} className="p-3 rounded-lg border text-sm">
                        <div className="flex items-center gap-2 mb-1">
                          <code className="text-xs bg-muted px-1 rounded">{r.sample_id}</code>
                          <Badge variant="outline" className="text-xs">{r.query_type}</Badge>
                          {r.error ? <XCircle className="h-3.5 w-3.5 text-destructive ml-auto" />
                            : <CheckCircle2 className="h-3.5 w-3.5 text-green-500 ml-auto" />}
                        </div>
                        <p className="font-medium">{r.query}</p>
                        {r.predicted_answer && (
                          <p className="text-muted-foreground mt-1 line-clamp-3">{r.predicted_answer}</p>
                        )}
                        {r.error && <p className="text-destructive text-xs mt-1">{r.error}</p>}
                        <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                          {r.cited_sources.length > 0 && <span>引用: {r.cited_sources.length}</span>}
                          {r.retrieved_ids.length > 0 && <span>检索: {r.retrieved_ids.length}</span>}
                          <span className="ml-auto">{(r.processing_time_ms / 1000).toFixed(1)}s</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}

// ── Main Page ──

export function EvaluationPage() {
  const [tab, setTab] = useState<Tab>('dataset')

  const tabs: { id: Tab; label: string; icon: typeof Database }[] = [
    { id: 'dataset', label: '数据集管理', icon: Database },
    { id: 'run', label: '运行评估', icon: Play },
    { id: 'results', label: '历史结果', icon: History },
  ]

  return (
    <div className="container mx-auto py-6 px-4 max-w-5xl">
      <div className="space-y-6">
        <Card>
          <CardContent className="py-3">
            <div className="flex items-center gap-1">
              {tabs.map(({ id, label, icon: Icon }) => (
                <Button
                  key={id}
                  variant={tab === id ? 'default' : 'ghost'}
                  size="sm"
                  onClick={() => setTab(id)}
                  className="gap-1.5"
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {tab === 'dataset' && <DatasetTab />}
        {tab === 'run' && <RunTab />}
        {tab === 'results' && <ResultsTab />}
      </div>
    </div>
  )
}
