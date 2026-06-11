import { useState, useCallback, useEffect } from 'react'
import { Brain, Github } from 'lucide-react'
import { UploadPanel } from '@/components/UploadPanel'
import { ChatPanel } from '@/components/ChatPanel'
import { StatsPanel } from '@/components/StatsPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'
import { Button } from '@/components/ui/button'
import { healthCheck } from '@/lib/api'

export function Home() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [isOnline, setIsOnline] = useState<boolean | null>(null)

  useEffect(() => {
    const check = async () => {
      const ok = await healthCheck()
      setIsOnline(ok)
    }
    check()
    const interval = setInterval(check, 10000)
    return () => clearInterval(interval)
  }, [])

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    )
  }, [])

  const handleUploadComplete = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-[calc(100vh-3rem)]">
        {/* Left sidebar: Branding + Status + Folder tree + Tag filter + Stats */}
        <div className="lg:col-span-2 space-y-4 overflow-y-auto">
          <a className="flex items-center gap-2 px-1" href="/">
            <Brain className="h-5 w-5 text-primary" />
            <span className="font-bold text-sm">Agentic-GraphRAG</span>
          </a>
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-1.5 text-xs">
              <span
                className={`h-2 w-2 rounded-full ${
                  isOnline === null
                    ? 'bg-gray-400 animate-pulse'
                    : isOnline
                      ? 'bg-green-500'
                      : 'bg-red-500'
                }`}
              />
              <span className="text-muted-foreground">
                {isOnline === null ? '检测中' : isOnline ? '后端在线' : '后端离线'}
              </span>
            </div>
            <Button variant="ghost" size="sm" asChild className="h-7 px-2 text-xs">
              <a href="https://github.com/microsoft/graphrag" target="_blank" rel="noopener noreferrer">
                <Github className="mr-1 h-3 w-3" />
                GraphRAG
              </a>
            </Button>
          </div>
          <FolderTree selectedFolder={selectedFolder} onSelect={setSelectedFolder} />
          <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
          <StatsPanel />
        </div>

        {/* Middle: Upload + Document list */}
        <div className="lg:col-span-3 space-y-4 overflow-y-auto">
          <UploadPanel folder={selectedFolder} onUploadComplete={handleUploadComplete} />
          <DocumentList folder={selectedFolder} tags={selectedTags} key={refreshKey} />
        </div>

        {/* Right: Chat */}
        <div className="lg:col-span-7">
          <ChatPanel folder={selectedFolder} tags={selectedTags} />
        </div>
      </div>
    </div>
  )
}
