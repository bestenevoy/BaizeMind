import { useState, useCallback } from 'react'
import { ChatPanel } from '@/components/ChatPanel'
import { StatsPanel } from '@/components/StatsPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'

export function Home() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    )
  }, [])

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-[calc(100vh-3rem)]">
        <div className="lg:col-span-2 space-y-4 overflow-y-auto">
          <FolderTree selectedFolder={selectedFolder} onSelect={setSelectedFolder} readonly showRefresh={false} />
          <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
          <StatsPanel />
        </div>

        <div className="lg:col-span-10">
          <ChatPanel folder={selectedFolder} tags={selectedTags} />
        </div>
      </div>
    </div>
  )
}
