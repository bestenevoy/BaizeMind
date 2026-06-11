import { useEffect, useState } from 'react'
import { FolderOpen, Folder, ChevronRight, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { listFolders, type FolderInfo } from '@/lib/api'

interface FolderTreeProps {
  selectedFolder: string | null
  onSelect: (folder: string | null) => void
}

export function FolderTree({ selectedFolder, onSelect }: FolderTreeProps) {
  const [folders, setFolders] = useState<FolderInfo[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['/']))

  useEffect(() => {
    listFolders().then(setFolders).catch(() => {})
  }, [])

  const toggle = (folder: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(folder)) next.delete(folder)
      else next.add(folder)
      return next
    })
  }

  const tree = buildTree(folders)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <FolderOpen className="h-4 w-4" />
          文件夹
        </CardTitle>
      </CardHeader>
      <CardContent className="p-2 space-y-0.5">
        <FolderNode
          node={tree}
          depth={0}
          selected={selectedFolder}
          expanded={expanded}
          onSelect={onSelect}
          onToggle={toggle}
        />
      </CardContent>
    </Card>
  )
}

interface TreeNode {
  name: string
  path: string
  count: number
  children: TreeNode[]
}

function buildTree(folders: FolderInfo[]): TreeNode {
  const root: TreeNode = { name: '全部', path: '', count: folders.reduce((s, f) => s + f.doc_count, 0), children: [] }
  const map = new Map<string, TreeNode>()
  map.set('', root)

  for (const f of folders) {
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

  return root
}

function FolderNode({
  node,
  depth,
  selected,
  expanded,
  onSelect,
  onToggle,
}: {
  node: TreeNode
  depth: number
  selected: string | null
  expanded: Set<string>
  onSelect: (folder: string | null) => void
  onToggle: (path: string) => void
}) {
  const hasChildren = node.children.length > 0
  const isExpanded = expanded.has(node.path) || node.path === ''
  const isSelected = selected === (node.path || null)

  return (
    <div>
      <button
        className={`flex items-center gap-1 w-full px-2 py-1 rounded text-sm hover:bg-accent transition-colors ${
          isSelected ? 'bg-accent text-accent-foreground font-medium' : ''
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => {
          onSelect(node.path || null)
          if (hasChildren) onToggle(node.path)
        }}
      >
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" />
          )
        ) : (
          <span className="w-3" />
        )}
        {node.path ? <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <FolderOpen className="h-3.5 w-3.5 shrink-0 text-primary" />}
        <span className="truncate">{node.name}</span>
        <span className="ml-auto text-xs text-muted-foreground">{node.count}</span>
      </button>
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
            />
          ))}
        </div>
      )}
    </div>
  )
}
