import { useEffect, useState, useCallback } from 'react'
import {
  FolderOpen, Folder, ChevronRight, ChevronDown, RefreshCw,
  Plus, Trash2, Pencil, GripHorizontal,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { listFolders, createFolder, deleteFolder, moveFolder, moveDocument } from '@/lib/api'
import type { FolderInfo, DocumentInfo } from '@/lib/api'

interface FolderTreeProps {
  selectedFolder: string | null
  onSelect: (folder: string | null) => void
  onChanged?: () => void
  showRefresh?: boolean
  readonly?: boolean
}

export function FolderTree({ selectedFolder, onSelect, onChanged, showRefresh = true, readonly = false }: FolderTreeProps) {
  const [folders, setFolders] = useState<FolderInfo[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
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
        if (next.size === 0) next.add('/')
        return next
      })
    } catch {}
  }, [])

  useEffect(() => { fetchFolders() }, [fetchFolders])

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteFolder(deleteTarget.folder)
      fetchFolders()
      onChanged?.()
      if (selectedFolder === deleteTarget.folder) onSelect(null)
    } catch {}
    setDeleteTarget(null)
  }

  const handleRename = async (newPath: string) => {
    if (!renameTarget || !newPath || newPath === renameTarget.folder) return
    try {
      await moveFolder(renameTarget.folder, newPath)
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
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={fetchFolders} title="刷新">
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-2 space-y-0.5">
        <FolderNode
          node={tree}
          depth={0}
          selected={selectedFolder}
          expanded={expanded}
          onSelect={onSelect}
          onToggle={(path) => setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(path)) next.delete(path)
            else next.add(path)
            return next
          })}
          onNewFolder={(parent) => { setNewFolderParent(parent); setShowNewFolder(true) }}
          onDeleteFolder={(f) => setDeleteTarget(f)}
          onRenameFolder={(f) => setRenameTarget(f)}
          readonly={readonly}
        />
      </CardContent>

      {/* New Folder Dialog */}
      {showNewFolder && (
        <Dialog open={showNewFolder} onOpenChange={(o) => { if (!o) setShowNewFolder(false) }}>
          <NewFolderDialog
            onSubmit={handleCreateFolder}
            onClose={() => setShowNewFolder(false)}
            parentPath={newFolderParent}
          />
        </Dialog>
      )}

      {/* Delete Confirm Dialog */}
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

      {/* Rename Dialog */}
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

// ── Dialog components ──

function NewFolderDialog({
  onSubmit, onClose, parentPath,
}: {
  onSubmit: (name: string) => void
  onClose: () => void
  parentPath: string
}) {
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
          <Input
            placeholder="文件夹名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
            autoFocus
          />
          {name && <p className="text-xs text-muted-foreground mt-1">路径: {fullPath}</p>}
        </div>
        <div>
          <Input
            placeholder="同时创建子目录 (可选)"
            value={nested}
            onChange={(e) => setNested(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={!name.trim()}>
            <Plus className="h-4 w-4 mr-1" />创建
          </Button>
        </div>
      </div>
    </DialogContent>
  )
}

function RenameDialog({
  currentPath, onSubmit, onClose,
}: {
  currentPath: string
  onSubmit: (newPath: string) => void
  onClose: () => void
}) {
  const [val, setVal] = useState(currentPath)

  useEffect(() => { setVal(currentPath) }, [currentPath])

  const handleSubmit = () => {
    if (!val.trim() || val === currentPath) {
      onClose()
      return
    }
    onSubmit(val)
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>移动/重命名文件夹</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">当前路径: {currentPath}</p>
        <Input
          placeholder="新路径，如 /docs/ai"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
          autoFocus
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={!val.trim() || val === currentPath}>
            <Pencil className="h-4 w-4 mr-1" />确定
          </Button>
        </div>
      </div>
    </DialogContent>
  )
}

// ── Tree structure ──

interface TreeNode {
  name: string
  path: string
  count: number
  children: TreeNode[]
}

function buildTree(folders: FolderInfo[]): TreeNode {
  const root: TreeNode = { name: '全部', path: '', count: 0, children: [] }
  const map = new Map<string, TreeNode>()
  map.set('', root)

  for (const f of folders) {
    if (f.folder === '/') {
      root.count = f.doc_count
      continue
    }
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

  // propagate counts upward from leaves
  function sumChildren(node: TreeNode) {
    let total = node.count
    for (const child of node.children) {
      sumChildren(child)
      total += child.count
    }
    if (node.children.length > 0) {
      node.count = total
    }
  }
  sumChildren(root)

  return root
}

// ── Folder node ──

function FolderNode({
  node, depth, selected, expanded, onSelect, onToggle, onNewFolder, onDeleteFolder, onRenameFolder, readonly,
}: {
  node: TreeNode
  depth: number
  selected: string | null
  expanded: Set<string>
  onSelect: (folder: string | null) => void
  onToggle: (path: string) => void
  onNewFolder: (parent: string) => void
  onDeleteFolder: (f: FolderInfo) => void
  onRenameFolder: (f: FolderInfo) => void
  readonly?: boolean
}) {
  const hasChildren = node.children.length > 0
  const isExpanded = expanded.has(node.path) || node.path === ''
  const isSelected = selected === (node.path || null)
  const isRoot = node.path === ''
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div>
      <div
        className={`group flex items-center gap-1 w-full rounded text-sm relative ${
          isSelected ? 'bg-accent text-accent-foreground font-medium' : 'hover:bg-accent'
        }`}
        style={{ paddingLeft: `${depth * 12 + (isRoot ? 4 : 8)}px` }}
      >
        {/* Expand/collapse */}
        {hasChildren || isRoot ? (
          <button
            className="shrink-0 py-1"
            onClick={(e) => { e.stopPropagation(); onToggle(node.path) }}
          >
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : (
          <span className="w-3 shrink-0" />
        )}

        {/* Main button */}
        <button
          className="flex items-center gap-1.5 flex-1 min-w-0 py-1 pr-1"
          onClick={() => onSelect(node.path || null)}
        >
          {isRoot ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-primary" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate">{node.name}</span>
          <span className="ml-auto text-xs text-muted-foreground shrink-0">{node.count || ''}</span>
        </button>

        {/* Context actions (non-root) */}
        {!isRoot && !readonly && (
          <div className="hidden group-hover:flex items-center gap-0.5 pr-0.5">
            <button
              className="p-0.5 rounded hover:bg-accent-foreground/10"
              title="新建子目录"
              onClick={(e) => { e.stopPropagation(); onNewFolder(node.path) }}
            >
              <Plus className="h-3 w-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-accent-foreground/10"
              title="移动/重命名"
              onClick={(e) => { e.stopPropagation(); onRenameFolder({ folder: node.path, doc_count: node.count }) }}
            >
              <Pencil className="h-3 w-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-destructive/10 text-destructive"
              title="删除文件夹"
              onClick={(e) => { e.stopPropagation(); onDeleteFolder({ folder: node.path, doc_count: node.count }) }}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <FolderNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selected={selected}
              expanded={expanded}
              onSelect={onSelect}
              onToggle={onToggle}
              onNewFolder={onNewFolder}
              onDeleteFolder={onDeleteFolder}
              onRenameFolder={onRenameFolder}
              readonly={readonly}
            />
          ))}
        </div>
      )}
    </div>
  )
}
