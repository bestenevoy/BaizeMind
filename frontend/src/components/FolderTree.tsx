import { useEffect, useState, useCallback, type ReactNode } from 'react'
import {
  FolderOpen, Folder, ChevronRight, ChevronDown, RefreshCw,
  Plus, Trash2, Pencil, FileText, Check,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { listFolders, listDocuments, createFolder, deleteFolder, moveFolder, moveDocument } from '@/lib/api'
import type { FolderInfo, DocumentInfo } from '@/lib/api'

interface FolderTreeProps {
  selectedFolder: string | null
  selectedDocId: string | null
  onSelectFolder: (folder: string | null) => void
  onSelectDoc: (docId: string | null) => void
  onChanged?: () => void
  showRefresh?: boolean
  readonly?: boolean
  showDocs?: boolean
}

export function FolderTree({ selectedFolder, selectedDocId, onSelectFolder, onSelectDoc, onChanged, showRefresh = true, readonly = false, showDocs = true }: FolderTreeProps) {
  const [folders, setFolders] = useState<FolderInfo[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [folderDocs, setFolderDocs] = useState<Record<string, DocumentInfo[]>>({})
  const [loadingDocs, setLoadingDocs] = useState<Set<string>>(new Set())
  const [showNewFolder, setShowNewFolder] = useState(false)
  const [newFolderParent, setNewFolderParent] = useState('/')
  const [deleteTarget, setDeleteTarget] = useState<FolderInfo | null>(null)
  const [renameTarget, setRenameTarget] = useState<FolderInfo | null>(null)

  const fetchFolders = useCallback(async () => {
    try {
      const data = await listFolders()
      setFolders(data)
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.size === 0) next.add('')
        return next
      })
    } catch {}
  }, [])

  useEffect(() => { fetchFolders() }, [fetchFolders])

  const loadDocs = useCallback(async (folderPath: string, force = false) => {
    if (loadingDocs.has(folderPath)) return
    setLoadingDocs(prev => new Set(prev).add(folderPath))
    try {
      const docs = folderPath ? await listDocuments(folderPath) : await listDocuments()
      setFolderDocs(prev => ({ ...prev, [folderPath]: docs }))
    } catch {}
    setLoadingDocs(prev => {
      const next = new Set(prev)
      next.delete(folderPath)
      return next
    })
  }, [loadingDocs])

  useEffect(() => {
    if (expanded.has('')) loadDocs('')
  }, [expanded.has('')])

  const handleToggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
        fetchFolders()
        if (showDocs) loadDocs(path)
      }
      return next
    })
  }, [fetchFolders, loadDocs, showDocs])

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteFolder(deleteTarget.folder)
      setFolderDocs(prev => {
        const next = { ...prev }
        delete next[deleteTarget.folder]
        return next
      })
      fetchFolders()
      onChanged?.()
      if (selectedFolder === deleteTarget.folder) onSelectFolder(null)
    } catch {}
    setDeleteTarget(null)
  }

  const handleRename = async (newPath: string) => {
    if (!renameTarget || !newPath || newPath === renameTarget.folder) return
    try {
      await moveFolder(renameTarget.folder, newPath)
      setFolderDocs(prev => {
        const next = { ...prev }
        delete next[renameTarget.folder]
        return next
      })
      fetchFolders()
      onChanged?.()
    } catch {}
    setRenameTarget(null)
  }

  const handleCreateFolder = async (name: string) => {
    if (!name.trim()) return
    const base = newFolderParent === '/' ? '' : newFolderParent
    const path = base + '/' + name.trim()
    try {
      await createFolder(path)
      fetchFolders()
      setExpanded((prev) => {
        const next = new Set(prev)
        next.add(newFolderParent)
        return next
      })
    } catch {}
    setShowNewFolder(false)
  }

  const tree = buildTree(folders)

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-1">
          <CardTitle className="text-sm flex items-center gap-2 flex-1">
            <FolderOpen className="h-4 w-4" />
            文件夹
          </CardTitle>
          {!readonly && (
            <Button
              variant="ghost" size="icon" className="h-6 w-6"
              onClick={() => { setNewFolderParent('/'); setShowNewFolder(true) }}
              title="新建文件夹"
            >
              <Plus className="h-3 w-3" />
            </Button>
          )}
          {showRefresh && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => { fetchFolders(); setFolderDocs({}); }} title="刷新">
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-2 space-y-0.5">
        <FolderNode
          node={tree}
          depth={0}
          selectedFolder={selectedFolder}
          selectedDocId={selectedDocId}
          expanded={expanded}
          folderDocs={folderDocs}
          loadingDocs={loadingDocs}
          onSelectFolder={onSelectFolder}
          onSelectDoc={onSelectDoc}
          onToggle={handleToggle}
          onNewFolder={(parent) => { setNewFolderParent(parent); setShowNewFolder(true) }}
          onDeleteFolder={(f) => setDeleteTarget(f)}
          onRenameFolder={(f) => setRenameTarget(f)}
          readonly={readonly}
          showDocs={showDocs}
        />
      </CardContent>

      {showNewFolder && (
        <Dialog open={showNewFolder} onOpenChange={(o) => { if (!o) setShowNewFolder(false) }}>
          <NewFolderDialog
            onSubmit={handleCreateFolder}
            onClose={() => setShowNewFolder(false)}
            parentPath={newFolderParent}
          />
        </Dialog>
      )}

      <Dialog open={!!deleteTarget} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除文件夹？</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            将删除 <code className="bg-muted px-1 rounded">{deleteTarget?.folder}</code>
            {deleteTarget && deleteTarget.doc_count > 0 ? ` 及其 ${deleteTarget.doc_count} 篇文档` : ''}，此操作不可撤销。
          </p>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete}>
              <Trash2 className="h-4 w-4 mr-1" />删除
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {renameTarget && (
        <Dialog open={!!renameTarget} onOpenChange={(o) => { if (!o) setRenameTarget(null) }}>
          <RenameDialog
            currentPath={renameTarget.folder}
            onSubmit={handleRename}
            onClose={() => setRenameTarget(null)}
          />
        </Dialog>
      )}
    </Card>
  )
}

function NewFolderDialog({ onSubmit, onClose, parentPath }: { onSubmit: (name: string) => void; onClose: () => void; parentPath: string }) {
  const [name, setName] = useState('')
  const [nested, setNested] = useState('')

  const fullPath = parentPath === '/' ? `/${name}` : `${parentPath}/${name}`

  const handleSubmit = () => {
    if (!name.trim()) return
    onSubmit(name)
    if (nested.trim()) onSubmit(`${name}/${nested}`)
    setName('')
    setNested('')
    onClose()
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>新建文件夹</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div>
          <label className="text-sm text-muted-foreground">位置: {parentPath}</label>
        </div>
        <div>
          <Input placeholder="文件夹名称" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }} autoFocus />
          {name && <p className="text-xs text-muted-foreground mt-1">路径: {fullPath}</p>}
        </div>
        <div>
          <Input placeholder="同时创建子目录 (可选)" value={nested} onChange={(e) => setNested(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={!name.trim()}><Plus className="h-4 w-4 mr-1" />创建</Button>
        </div>
      </div>
    </DialogContent>
  )
}

function RenameDialog({ currentPath, onSubmit, onClose }: { currentPath: string; onSubmit: (newPath: string) => void; onClose: () => void }) {
  const [val, setVal] = useState(currentPath)
  useEffect(() => { setVal(currentPath) }, [currentPath])
  const handleSubmit = () => {
    if (!val.trim() || val === currentPath) { onClose(); return }
    onSubmit(val)
  }
  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>移动/重命名文件夹</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">当前路径: {currentPath}</p>
        <Input placeholder="新路径，如 /docs/ai" value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }} autoFocus />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={!val.trim() || val === currentPath}><Pencil className="h-4 w-4 mr-1" />确定</Button>
        </div>
      </div>
    </DialogContent>
  )
}

interface TreeNode { name: string; path: string; count: number; children: TreeNode[] }

function buildTree(folders: FolderInfo[]): TreeNode {
  const root: TreeNode = { name: '全部', path: '', count: 0, children: [] }
  const map = new Map<string, TreeNode>()
  map.set('', root)
  for (const f of folders) {
    if (f.folder === '/') { root.count = f.doc_count; continue }
    const parts = f.folder.split('/').filter(Boolean)
    let parentPath = ''
    for (const part of parts) {
      const currentPath = parentPath ? `${parentPath}/${part}` : `/${part}`
      if (!map.has(currentPath)) {
        const node: TreeNode = { name: part, path: currentPath, count: 0, children: [] }
        map.set(currentPath, node)
        const parent = map.get(parentPath)
        if (parent) parent.children.push(node)
      }
      parentPath = currentPath
    }
    const leaf = map.get(f.folder)
    if (leaf) leaf.count = f.doc_count
  }
  function sumChildren(node: TreeNode) {
    let total = node.count
    for (const child of node.children) { sumChildren(child); total += child.count }
    if (node.children.length > 0) node.count = total
  }
  sumChildren(root)
  return root
}

function FolderNode({
  node, depth, selectedFolder, selectedDocId, expanded, folderDocs, loadingDocs,
  onSelectFolder, onSelectDoc, onToggle, onNewFolder, onDeleteFolder, onRenameFolder, readonly, showDocs = true,
}: {
  node: TreeNode; depth: number; selectedFolder: string | null; selectedDocId: string | null
  expanded: Set<string>; folderDocs: Record<string, DocumentInfo[]>; loadingDocs: Set<string>
  onSelectFolder: (folder: string | null) => void; onSelectDoc: (docId: string | null) => void
  onToggle: (path: string) => void; onNewFolder: (parent: string) => void
  onDeleteFolder: (f: FolderInfo) => void; onRenameFolder: (f: FolderInfo) => void; readonly?: boolean; showDocs?: boolean
}) {
  const ctx: RenderCtx = { selectedFolder, selectedDocId, expanded, folderDocs, loadingDocs,
    onToggle, onNewFolder, onDeleteFolder, onRenameFolder, readonly, showDocs, onSelectFolder, onSelectDoc }
  return <>{buildRows(node, depth, ctx)}</>
}

interface RenderCtx {
  selectedFolder: string | null; selectedDocId: string | null
  expanded: Set<string>; folderDocs: Record<string, DocumentInfo[]>; loadingDocs: Set<string>
  onToggle: (path: string) => void; onNewFolder: (parent: string) => void
  onDeleteFolder: (f: FolderInfo) => void; onRenameFolder: (f: FolderInfo) => void
  readonly: boolean | undefined; showDocs: boolean
  onSelectFolder: (folder: string | null) => void; onSelectDoc: (docId: string | null) => void
}

function renderFolderRow(node: TreeNode, depth: number, pad: number, isExpanded: boolean, isSelected: boolean, hasChildren: boolean, isRoot: boolean, ctx: RenderCtx): ReactNode {
  const depthColors = ['text-blue-400', 'text-emerald-400', 'text-amber-400', 'text-purple-400', 'text-rose-400']
  return (
    <div key={node.path || '__root__'}
      className={`group flex items-center w-full rounded text-sm relative cursor-pointer transition-colors ${
        isSelected ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted/50'
      }`}
      style={{ paddingLeft: `${pad}px` }}
      onClick={() => ctx.onSelectFolder(node.path || null)}>
      {(hasChildren || isRoot) ? (
        <span
          className="shrink-0 py-1.5 hover:text-foreground transition-colors"
          onClick={(e) => { e.stopPropagation(); ctx.onToggle(node.path) }}
          role="button"
        >
          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      ) : (
        <span className="w-3 shrink-0" />
      )}
      <span className="flex items-center flex-1 min-w-0 py-1.5 pr-1" style={{ marginLeft: 2 }}>
        {isRoot ? <FolderOpen className={`h-3.5 w-3.5 shrink-0 ${isSelected ? 'text-primary' : 'text-primary/70'}`} />
          : <Folder className={`h-3.5 w-3.5 shrink-0 ${isSelected ? depthColors[depth % depthColors.length] : 'text-muted-foreground/60'}`} />}
        <span className="truncate" style={{ marginLeft: 6 }}>{node.name}</span>
        {node.count > 0 && <span className="ml-auto text-[11px] text-muted-foreground shrink-0 tabular-nums bg-muted/50 px-1.5 py-0.5 rounded-full">{node.count}</span>}
      </span>
      {!isRoot && !ctx.readonly && (
        <div className="hidden group-hover:flex items-center gap-0.5 pr-1">
          <button className="p-0.5 rounded hover:bg-accent-foreground/10 transition-colors" title="新建子目录" onClick={(e) => { e.stopPropagation(); ctx.onNewFolder(node.path) }}><Plus className="h-3 w-3" /></button>
          <button className="p-0.5 rounded hover:bg-accent-foreground/10 transition-colors" title="移动/重命名" onClick={(e) => { e.stopPropagation(); ctx.onRenameFolder({ folder: node.path, doc_count: node.count }) }}><Pencil className="h-3 w-3" /></button>
          <button className="p-0.5 rounded hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive" title="删除文件夹" onClick={(e) => { e.stopPropagation(); ctx.onDeleteFolder({ folder: node.path, doc_count: node.count }) }}><Trash2 className="h-3 w-3" /></button>
        </div>
      )}
    </div>
  )
}

function renderDocRows(node: TreeNode, depth: number, docPad: number, ctx: RenderCtx): ReactNode[] {
  const rows: ReactNode[] = []
  const docs = ctx.folderDocs[node.path] || []
  const isLoadingDocs = ctx.loadingDocs.has(node.path)

  if (isLoadingDocs) {
    rows.push(
      <div key={`${node.path}__loading`} className="flex items-center py-1" style={{ paddingLeft: `${docPad}px` }}>
        <span className="w-3 shrink-0" />
        <span className="text-xs text-muted-foreground animate-pulse" style={{ marginLeft: 2 }}>加载中...</span>
      </div>
    )
  }
  for (const doc of docs) {
    rows.push(
      <div key={doc.doc_id}
        className={`group flex items-center w-full rounded text-xs py-1 cursor-pointer transition-colors ${
          ctx.selectedDocId === doc.doc_id
            ? 'bg-primary/10 text-primary font-medium'
            : 'hover:bg-muted/50'
        }`}
        style={{ paddingLeft: `${docPad}px`, paddingRight: 4 }}
        onClick={() => ctx.onSelectDoc(doc.doc_id)}>
        <span className="w-3 shrink-0" />
        <span className="flex items-center flex-1 min-w-0" style={{ marginLeft: 2 }}>
          {ctx.selectedDocId === doc.doc_id ? (
            <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
          ) : (
            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate" style={{ marginLeft: 6 }}>{doc.filename}</span>
        </span>
        {doc.status !== 'completed' && <span className="text-[10px] text-amber-500 shrink-0">{doc.status}</span>}
      </div>
    )
  }
  return rows
}

function buildRows(node: TreeNode, depth: number, ctx: RenderCtx): ReactNode[] {
  const rows: ReactNode[] = []
  const hasChildren = node.children.length > 0
  const isRoot = node.path === ''
  const isExpanded = ctx.expanded.has(node.path) || (isRoot && ctx.expanded.has(''))
  const isSelected = isRoot
    ? (ctx.selectedFolder === null && ctx.selectedDocId === null)
    : ctx.selectedFolder === node.path
  const pad = depth * 14 + (isRoot ? 4 : 6)
  const docPad = (depth + 1) * 14 + 6

  rows.push(renderFolderRow(node, depth, pad, isExpanded, isSelected, hasChildren, isRoot, ctx))

  if (hasChildren && isExpanded) {
    for (const child of node.children) {
      rows.push(...buildRows(child, depth + 1, ctx))
    }
  }
  if (isExpanded && ctx.showDocs) {
    rows.push(...renderDocRows(node, depth, docPad, ctx))
  }
  return rows
}
