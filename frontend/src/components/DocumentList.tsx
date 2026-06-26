import { useEffect, useState, useCallback } from 'react'
import { FileText, Trash2, CheckCircle2, Loader2, AlertCircle, Tag, RotateCcw, Eye, X, ExternalLink, FileImage, FolderInput, Layers } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { listDocuments, deleteDocument, retryDocument, getDocumentContent, getDocumentChunks, moveDocument, listFolders, type DocumentInfo, type DocumentContent, type DocumentChunks, type FolderInfo } from '@/lib/api'

interface DocumentListProps {
  folder: string | null
  tags: string[]
  onRefresh?: () => void
}

export function DocumentList({ folder, tags, onRefresh }: DocumentListProps) {
  const [docs, setDocs] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<DocumentContent | null>(null)
  const [previewChunks, setPreviewChunks] = useState<DocumentChunks | null>(null)
  const [activeTab, setActiveTab] = useState<'markdown' | 'original' | 'chunks'>('markdown')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [retrying, setRetrying] = useState<string | null>(null)
  const [moveTarget, setMoveTarget] = useState<DocumentInfo | null>(null)
  const [moveToFolder, setMoveToFolder] = useState('')
  const [folderOptions, setFolderOptions] = useState<FolderInfo[]>([])

  const fetchDocs = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listDocuments(folder || undefined, tags.length ? tags : undefined)
      setDocs(result)
    } catch {
      setDocs([])
    } finally {
      setLoading(false)
    }
  }, [folder, tags.join(',')])

  useEffect(() => {
    fetchDocs()
  }, [fetchDocs])

  useEffect(() => {
    if (onRefresh) onRefresh()
  }, [onRefresh])

  const handleDelete = async (docId: string) => {
    if (!confirm('确认删除该文档？')) return
    try {
      await deleteDocument(docId)
      fetchDocs()
    } catch {}
  }

  const handleMove = async () => {
    if (!moveTarget || !moveToFolder.trim()) return
    try {
      await moveDocument(moveTarget.doc_id, moveToFolder)
      setMoveTarget(null)
      setMoveToFolder('')
      fetchDocs()
    } catch {}
  }

  const openMoveDialog = async (doc: DocumentInfo) => {
    setMoveTarget(doc)
    setMoveToFolder(doc.folder)
    try {
      const f = await listFolders()
      setFolderOptions(f)
    } catch {
      setFolderOptions([])
    }
  }

  const handleRetry = async (docId: string) => {
    setRetrying(docId)
    try {
      await retryDocument(docId)
      fetchDocs()
    } catch (e) {
      alert(`重试失败: ${e}`)
    } finally {
      setRetrying(null)
    }
  }

  const handlePreview = async (docId: string) => {
    setPreviewLoading(true)
    setActiveTab('markdown')
    try {
      const content = await getDocumentContent(docId)
      setPreviewDoc(content)
      try {
        const chunks = await getDocumentChunks(docId)
        setPreviewChunks(chunks)
      } catch {
        setPreviewChunks(null)
      }
    } catch (e) {
      alert(`获取内容失败: ${e}`)
    } finally {
      setPreviewLoading(false)
    }
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
      case 'processing':
      case 'pending':
        return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
      case 'failed':
        return <AlertCircle className="h-3.5 w-3.5 text-destructive" />
      default:
        return null
    }
  }

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText className="h-4 w-4" />
            文档列表
            <span className="text-muted-foreground font-normal">({docs.length})</span>
          </CardTitle>
        </div>
      </CardHeader>
      <ScrollArea className="max-h-[300px]">
        <CardContent className="p-2 space-y-1">
          {docs.length === 0 && !loading && (
            <p className="text-sm text-muted-foreground text-center py-4">暂无文档</p>
          )}
          {docs.map((doc) => (
            <div key={doc.doc_id} className="flex items-start gap-2 p-2 rounded-md hover:bg-muted/50 group">
              <FileText className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm truncate">{doc.filename}</span>
                  {statusIcon(doc.status)}
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-xs text-muted-foreground">{doc.folder}</span>
                  {doc.chunk_count > 0 && (
                    <span className="text-xs text-muted-foreground">· {doc.chunk_count} chunks</span>
                  )}
                </div>
                {(doc.status === 'processing' || doc.status === 'pending') && doc.processing_stage && (
                  <div className="flex items-center gap-1 mt-0.5">
                    <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">{doc.processing_stage}</span>
                  </div>
                )}
                {doc.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {doc.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                        <Tag className="h-2.5 w-2.5 mr-0.5" />
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
                {doc.error && <p className="text-xs text-destructive mt-0.5">{doc.error}</p>}
              </div>
              <div className="flex items-center gap-0.5 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => handlePreview(doc.doc_id)}
                  title="查看内容"
                >
                  <Eye className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => openMoveDialog(doc)}
                  title="移动文件"
                >
                  <FolderInput className="h-3 w-3" />
                </Button>
                {(doc.status === 'failed' || doc.status === 'completed') && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleRetry(doc.doc_id)}
                    disabled={retrying === doc.doc_id}
                    title="重试"
                  >
                    {retrying === doc.doc_id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <RotateCcw className="h-3 w-3" />
                    )}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => handleDelete(doc.doc_id)}
                >
                  <Trash2 className="h-3 w-3 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </ScrollArea>

      {previewLoading && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Loader2 className="h-8 w-8 animate-spin text-white" />
        </div>
      )}

      {previewDoc && (
        <div className="fixed inset-0 bg-black/50 flex items-start justify-center z-50 pt-10 px-4" onClick={() => { setPreviewDoc(null); setPreviewChunks(null) }}>
          <div className="bg-background rounded-lg shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-semibold">文档详情 - {previewDoc.filename}</h3>
              <div className="flex items-center gap-2">
                <Button variant={activeTab === 'markdown' ? 'secondary' : 'ghost'} size="sm" onClick={() => setActiveTab('markdown')}>
                  <FileText className="h-3.5 w-3.5 mr-1" />Markdown
                </Button>
                <Button variant={activeTab === 'original' ? 'secondary' : 'ghost'} size="sm" onClick={() => setActiveTab('original')}>
                  <FileImage className="h-3.5 w-3.5 mr-1" />原始
                </Button>
                <Button variant={activeTab === 'chunks' ? 'secondary' : 'ghost'} size="sm" onClick={() => setActiveTab('chunks')}>
                  <Layers className="h-3.5 w-3.5 mr-1" />Chunks{previewChunks ? ` (${previewChunks.total})` : ''}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => { setPreviewDoc(null); setPreviewChunks(null) }}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-4">
              {activeTab === 'markdown' && (
                <pre className="text-xs bg-muted/50 rounded p-3 whitespace-pre-wrap break-all max-h-[60vh] overflow-auto">
                  {previewDoc.parsed_markdown || '(空)'}
                </pre>
              )}
              {activeTab === 'original' && (
                <div>
                  {previewDoc.is_binary && previewDoc.raw_url ? (
                    <div>
                      {previewDoc.file_ext.match(/\.(png|jpg|jpeg|gif|webp|bmp|svg)$/) ? (
                        <div className="flex flex-col items-center gap-2">
                          <img
                            src={previewDoc.raw_url}
                            alt={previewDoc.filename}
                            className="max-w-full max-h-[60vh] object-contain rounded border"
                          />
                          <p className="text-xs text-muted-foreground">
                            图片 ({previewDoc.file_ext}) · {previewDoc.file_size_kb.toFixed(0)} KB
                          </p>
                        </div>
                      ) : previewDoc.file_ext.match(/\.(pdf)$/i) ? (
                        <iframe
                          src={previewDoc.raw_url}
                          className="w-full h-[60vh] border rounded"
                          title={previewDoc.filename}
                        />
                      ) : (
                        <div className="flex items-center gap-2 bg-muted/50 rounded p-4">
                          <FileText className="h-8 w-8 text-muted-foreground" />
                          <div>
                            <p className="text-sm">{previewDoc.original_content}</p>
                            <a
                              href={previewDoc.raw_url}
                              download
                              className="text-sm text-primary hover:underline flex items-center gap-1 mt-1"
                            >
                              <ExternalLink className="h-3 w-3" />
                              下载文件
                            </a>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <pre className="text-xs bg-muted/50 rounded p-3 whitespace-pre-wrap break-all max-h-[60vh] overflow-auto">
                      {previewDoc.original_content || '(空)'}
                    </pre>
                  )}
                </div>
              )}
              {activeTab === 'chunks' && (
                <div className="space-y-3">
                  {previewChunks === null ? (
                    <p className="text-sm text-muted-foreground text-center py-4">加载中...</p>
                  ) : previewChunks.chunks.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">暂无 Chunk 数据</p>
                  ) : (
                    previewChunks.chunks.map((chunk, idx) => (
                      <div key={chunk.chunk_id} className="border rounded-lg p-3 hover:bg-muted/30 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">#{idx + 1}</span>
                            <span className="text-xs font-mono text-muted-foreground">{chunk.chunk_id}</span>
                          </div>
                          {chunk.heading && (
                            <span className="text-xs text-muted-foreground bg-cyan-50 dark:bg-cyan-950/40 px-1.5 py-0.5 rounded">
                              {chunk.heading}
                            </span>
                          )}
                        </div>
                        <pre className="text-xs whitespace-pre-wrap break-all leading-relaxed max-h-[200px] overflow-auto">
                          {chunk.text}
                        </pre>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Move Document Dialog */}
      <Dialog open={!!moveTarget} onOpenChange={(o) => { if (!o) setMoveTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>移动文件</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm">
              <code className="bg-muted px-1 rounded">{moveTarget?.filename}</code>
              <span className="text-muted-foreground"> 当前: </span>
              <code className="bg-muted px-1 rounded">{moveTarget?.folder}</code>
            </p>
            <div>
              <label className="text-sm font-medium">目标文件夹</label>
              <div className="max-h-48 overflow-y-auto border rounded-md mt-1">
                {folderOptions.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-3">加载中...</p>
                ) : (
                  folderOptions.map((f) => (
                    <button
                      key={f.folder}
                      className={`block w-full text-left text-sm px-3 py-2 hover:bg-accent transition-colors cursor-pointer flex items-center gap-2 ${
                        moveToFolder === f.folder ? 'bg-accent text-accent-foreground font-medium' : ''
                      }`}
                      onClick={() => setMoveToFolder(f.folder)}
                    >
                      <svg className="h-3.5 w-3.5 shrink-0 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                      </svg>
                      <span className="flex-1 truncate">{f.folder}</span>
                      <span className="text-xs text-muted-foreground">{f.doc_count > 0 ? f.doc_count : ''}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setMoveTarget(null)}>取消</Button>
              <Button onClick={handleMove} disabled={!moveToFolder.trim() || moveToFolder === moveTarget?.folder}>
                <FolderInput className="h-4 w-4 mr-1" />移动
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
