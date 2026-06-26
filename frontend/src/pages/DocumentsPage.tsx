import { useState, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Upload, FileText, BeakerIcon } from 'lucide-react'
import { UploadPanel } from '@/components/UploadPanel'
import { FolderTree } from '@/components/FolderTree'
import { TagFilter } from '@/components/TagFilter'
import { DocumentList } from '@/components/DocumentList'
import { SearchDebugPanel } from '@/components/SearchDebugPanel'
import { Button } from '@/components/ui/button'
import { useFolderFilter } from '@/hooks/useFolderFilter'
import { useAuth } from '@/hooks/useAuth'
import { getUploadQuota, type UploadQuota } from '@/lib/api'

export function DocumentsPage() {
  const { selectedFolder, selectedDocId, selectedTags, toggleTag, selectFolder, selectDoc } = useFolderFilter()
  const [refreshKey, setRefreshKey] = useState(0)
  const [showUpload, setShowUpload] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') || 'docs'
  const setActiveTab = (tab: string) => setSearchParams({ tab })
  const { canUpload, isGuest, isUser, user } = useAuth()
  const [quota, setQuota] = useState<UploadQuota | null>(null)

  const refreshQuota = useCallback(async () => {
    if (!isUser) return
    try {
      setQuota(await getUploadQuota())
    } catch {
      /* ignore */
    }
  }, [isUser])

  useEffect(() => {
    refreshQuota()
  }, [refreshQuota, user?.user_id])

  const handleFolderChanged = useCallback(() => setRefreshKey(k => k + 1), [])
  const handleUploadComplete = useCallback(() => {
    setRefreshKey(k => k + 1)
    refreshQuota()
  }, [refreshQuota])

  return (
    <div className="container mx-auto pt-4 px-4 flex flex-col min-h-0 flex-1">
      <div className="flex items-center gap-1 flex-none border-b mb-4">
        {([
          { id: 'docs', label: '文档列表', icon: FileText },
          { id: 'search', label: '检索测试', icon: BeakerIcon },
        ] as const).map((tab) => {
          const Icon = tab.icon
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </button>
          )
        })}
      </div>
          <div className={activeTab === 'search' ? 'flex-1 min-h-0' : 'hidden'}>
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
                  readonly={!canUpload}
                />
              }
              tagFilter={<TagFilter selectedTags={selectedTags} onToggle={toggleTag} />}
            />
          </div>

          <div className={activeTab === 'docs' ? 'grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1 min-h-0' : 'hidden'}>
            <div className="lg:col-span-2 space-y-4 overflow-y-auto">
              <FolderTree
                selectedFolder={selectedFolder}
                selectedDocId={null}
                onSelectFolder={selectFolder}
                onSelectDoc={() => {}}
                onChanged={handleFolderChanged}
                showDocs={false}
                readonly={!canUpload}
              />
              <TagFilter selectedTags={selectedTags} onToggle={toggleTag} />
            </div>

            <div className="lg:col-span-10 min-h-0 overflow-y-auto">
              <div className="flex items-center justify-end mb-2 gap-2">
                {isUser && quota && (
                  <span className="text-xs text-muted-foreground">
                    今日上传：{quota.used}/{quota.limit}
                    {quota.remaining <= 0 && <span className="text-destructive ml-1">（已达上限）</span>}
                  </span>
                )}
                {isGuest && (
                  <span className="text-xs text-muted-foreground">访客模式：仅可查看，不可上传</span>
                )}
                {canUpload && (
                  <Button size="sm" onClick={() => setShowUpload(true)} disabled={!!quota && quota.remaining <= 0}>
                    <Upload className="h-4 w-4 mr-1" />
                    上传
                  </Button>
                )}
              </div>
              <DocumentList folder={selectedFolder} tags={selectedTags} key={refreshKey} />
            </div>
          </div>

          <UploadPanel
            folder={selectedFolder}
            open={showUpload}
            onOpenChange={setShowUpload}
            onUploadComplete={handleUploadComplete}
          />
      </div>
    )
}

