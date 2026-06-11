import { useState, useCallback } from 'react'
import { UploadPanel } from '@/components/UploadPanel'
import { ChatPanel } from '@/components/ChatPanel'
import { StatsPanel } from '@/components/StatsPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'

export function Home() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

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
        {/* Left sidebar: Folder tree + Tag filter + Stats */}
        <div className="lg:col-span-2 space-y-4 overflow-y-auto">
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
