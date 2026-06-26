import { ChatPanel } from '@/components/ChatPanel'
import { StatsPanel } from '@/components/StatsPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { useFolderFilter } from '@/hooks/useFolderFilter'

export function Home() {
  const { selectedFolder, selectedDocId, selectedTags, toggleTag, selectFolder, selectDoc } = useFolderFilter()

  return (
    <div className="chat-theme container mx-auto py-6 px-4 flex flex-col min-h-0 flex-1">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1 min-h-0">
        <div className="lg:col-span-3 space-y-4 overflow-y-auto">
          <FolderTree
            selectedFolder={selectedFolder}
            selectedDocId={selectedDocId}
            onSelectFolder={selectFolder}
            onSelectDoc={selectDoc}
            readonly
            showRefresh={false}
          />
          <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
          <StatsPanel />
        </div>

        <div className="lg:col-span-7 lg:col-start-5 min-h-0 overflow-hidden">
          <ChatPanel folder={selectedFolder} docId={selectedDocId} tags={selectedTags} />
        </div>
      </div>
    </div>
  )
}
