import { useState, useCallback } from 'react'

export function useFolderFilter() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [selectedTags, setSelectedTags] = useState<string[]>([])

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    )
  }, [])

  const selectFolder = useCallback((folder: string | null) => {
    setSelectedFolder(folder)
    if (folder) setSelectedDocId(null)
  }, [])

  const selectDoc = useCallback((docId: string | null) => {
    setSelectedDocId(docId)
    if (docId) setSelectedFolder(null)
  }, [])

  const resetFilters = useCallback(() => {
    setSelectedFolder(null)
    setSelectedDocId(null)
    setSelectedTags([])
  }, [])

  return { selectedFolder, selectedDocId, selectedTags, toggleTag, selectFolder, selectDoc, resetFilters }
}
