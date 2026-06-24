import { useState, useCallback } from 'react'
import { Upload, FileText, BeakerIcon } from 'lucide-react'
import { UploadPanel } from '@/components/UploadPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'
import { SearchDebugPanel } from '@/components/SearchDebugPanel'
import { Button } from '@/components/ui/button'
import { useFolderFilter } from '@/hooks/useFolderFilter'

export function DocumentsPage() {
  const { selectedFolder, selectedDocId, selectedTags, toggleTag, selectFolder, selectDoc } = useFolderFilter()
  const [refreshKey, setRefreshKey] = useState(0)
  const [showUpload, setShowUpload] = useState(false)
  const [activeTab, setActiveTab] = useState<'docs' | 'search'>('docs')

  const handleFolderChanged = useCallback(() => setRefreshKey(k => k + 1), [])
  const handleUploadComplete = useCallback(() => setRefreshKey(k => k + 1), [])

  return (
    <div className="container mx-auto pt-4 px-4 flex flex-col min-h-0 h-full">
      <div className="flex items-end gap-3 flex-none pb-3 border-b">
            <button
              onClick={() => setActiveTab('docs')}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md border border-b-0 transition-colors ${
                activeTab === 'docs'
                  ? 'bg-background text-foreground border-border font-medium'
                  : 'text-muted-foreground hover:text-foreground border-transparent'
              }`}
            >
              <FileText className="h-4 w-4" />
              文档列表
            </button>
            <button
              onClick={() => setActiveTab('search')}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md border border-b-0 transition-colors ${
                activeTab === 'search'
                  ? 'bg-background text-foreground border-border font-medium'
                  : 'text-muted-foreground hover:text-foreground border-transparent'
              }`}
            >
              <BeakerIcon className="h-4 w-4" />
              检索测试
            </button>
            <div className="flex-1 border-b" />
          </div>
          {(activeTab === 'docs' || activeTab === 'search') && (
            activeTab === 'search' ? (
              <div className="flex-1 min-h-0 pt-3">
                <SearchDebugPanel
                  folder={selectedFolder}
                  docId={selectedDocId}
                  tags={selectedTags}
                  folderTree={
                    <FolderTree
                      selectedFolder={selectedFolder}
                      selectedDocId={selectedDocId}
                      onSelectFolder={selectFolder}
                      onSelectDoc={selectDoc}
                      onChanged={handleFolderChanged}
                    />
                  }
                  tagFilter={<TagFilter selectedTags={selectedTags} onToggle={toggleTag} />}
                />
              </div>
            ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1 min-h-0 pt-3">
            <div className="lg:col-span-2 space-y-4 overflow-y-auto">
              <FolderTree
                selectedFolder={selectedFolder}
                selectedDocId={null}
                onSelectFolder={selectFolder}
                onSelectDoc={() => {}}
                onChanged={handleFolderChanged}
                showDocs={false}
              />
              <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
            </div>

            <div className="lg:col-span-10 overflow-y-auto">
              {activeTab === 'docs' ? (
                <>
                  <div className="flex justify-end mb-2">
                    <Button size="sm" onClick={() => setShowUpload(true)}>
                      <Upload className="h-4 w-4 mr-1" />
                      上传
                    </Button>
                  </div>
                  <DocumentList folder={selectedFolder} tags={selectedTags} key={refreshKey} />
                </>
              ) : null}
            </div>
          </div>
          ))}

          <UploadPanel
            folder={selectedFolder}
            open={showUpload}
            onOpenChange={setShowUpload}
            onUploadComplete={handleUploadComplete}
          />
      </div>
    )
}

