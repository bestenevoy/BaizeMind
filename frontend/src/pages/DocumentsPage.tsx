import { useState, useCallback } from 'react'
import { Upload } from 'lucide-react'
import { UploadPanel } from '@/components/UploadPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'
import { Button } from '@/components/ui/button'

export function DocumentsPage() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [showUpload, setShowUpload] = useState(false)

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
        <div className="lg:col-span-2 space-y-4 overflow-y-auto">
          <FolderTree selectedFolder={selectedFolder} onSelect={setSelectedFolder} />
          <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
        </div>

        <div className="lg:col-span-10 space-y-4 overflow-y-auto">
          <Button className="w-full md:w-64" size="lg" onClick={() => setShowUpload(true)}>
            <Upload className="h-5 w-5 mr-2" />
            上传文档
          </Button>
          <DocumentList folder={selectedFolder} tags={selectedTags} key={refreshKey} />
        </div>

        <UploadPanel
          folder={selectedFolder}
          open={showUpload}
          onOpenChange={setShowUpload}
          onUploadComplete={handleUploadComplete}
        />
      </div>
    </div>
  )
}
