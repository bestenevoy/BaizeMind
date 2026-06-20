import { useState, useRef } from 'react'
import { Upload, File, X, CheckCircle2, Loader2, FolderPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { uploadDocument, getDocumentStatus } from '@/lib/api'

interface UploadedDoc {
  doc_id: string
  filename: string
  status: string
  progress: number
  stage?: string
  error?: string
}

interface UploadPanelProps {
  folder: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onUploadComplete?: () => void
}

export function UploadPanel({ folder, open, onOpenChange, onUploadComplete }: UploadPanelProps) {
  const [docs, setDocs] = useState<UploadedDoc[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [customFolder, setCustomFolder] = useState('')
  const [showFolderInput, setShowFolderInput] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const targetFolder = (customFolder || folder || '/').replace(/^\/?(.*)/, '/$1').replace(/\/$/, '') || '/'

  const handleFiles = async (files: FileList | null) => {
    if (!files) return
    const fileArray = Array.from(files)

    for (const file of fileArray) {
      const tempId = `temp-${Date.now()}-${file.name}`
      setDocs((prev) => [...prev, { doc_id: tempId, filename: file.name, status: 'uploading', progress: 0 }])

      try {
        const result = await uploadDocument(file, targetFolder)
        setDocs((prev) =>
          prev.map((d) =>
            d.doc_id === tempId ? { ...d, doc_id: result.doc_id, status: 'processing', progress: 25 } : d
          )
        )
        pollStatus(result.doc_id)
      } catch (err) {
        setDocs((prev) =>
          prev.map((d) =>
            d.doc_id === tempId ? { ...d, status: 'failed', progress: 0, error: String(err) } : d
          )
        )
      }
    }
  }

  const pollStatus = (docId: string) => {
    const interval = setInterval(async () => {
      try {
        const status = await getDocumentStatus(docId)
        setDocs((prev) =>
          prev.map((d) => {
            if (d.doc_id !== docId) return d
            if (status.status === 'completed') {
              clearInterval(interval)
              onUploadComplete?.()
              return { ...d, status: 'completed', progress: 100 }
            }
            if (status.status === 'failed') {
              clearInterval(interval)
              return { ...d, status: 'failed', progress: 0, error: status.error }
            }
            return { ...d, progress: Math.min(d.progress + 15, 90), stage: status.processing_stage || undefined }
          })
        )
      } catch {
        clearInterval(interval)
      }
    }, 3000)
  }

  const removeDoc = (docId: string) => {
    setDocs((prev) => prev.filter((d) => d.doc_id !== docId))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5" />
              文档上传
            </DialogTitle>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setShowFolderInput(!showFolderInput)}>
              <FolderPlus className="h-4 w-4" />
            </Button>
          </div>
          <DialogDescription>
            上传到: <span className="font-medium">{targetFolder}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          {showFolderInput && (
            <div className="flex gap-2">
              <Input
                placeholder="自定义文件夹路径，如 /技术文档/AI"
                value={customFolder}
                onChange={(e) => setCustomFolder(e.target.value)}
                className="text-sm"
              />
              {customFolder && (
                <Button variant="ghost" size="sm" onClick={() => setCustomFolder('')}>
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}

          <div
            className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
              isDragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50'
            }`}
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setIsDragging(false)
              handleFiles(e.dataTransfer.files)
            }}
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">拖拽文件到此处，或点击选择</p>
            <p className="text-xs text-muted-foreground mt-1">支持 PDF, Word, Excel, PPT, 图片, TXT</p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.txt,.md"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
          </div>

          {docs.length > 0 && (
            <div className="space-y-2">
              {docs.map((doc) => (
                <div key={doc.doc_id} className="flex items-center gap-3 p-2 rounded-md bg-muted/50">
                  <File className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{doc.filename}</p>
                    {doc.status === 'processing' && (
                      <>
                        <Progress value={doc.progress} className="h-1 mt-1" />
                        {doc.stage && <p className="text-xs text-muted-foreground mt-0.5">{doc.stage}</p>}
                      </>
                    )}
                    {doc.error && <p className="text-xs text-destructive mt-1">{doc.error}</p>}
                  </div>
                  <div className="shrink-0">
                    {doc.status === 'completed' && <CheckCircle2 className="h-4 w-4 text-green-500" />}
                    {doc.status === 'processing' && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
                    {doc.status === 'failed' && (
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeDoc(doc.doc_id)}>
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
