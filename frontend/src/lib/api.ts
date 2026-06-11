const API_BASE = '/api/v1'

export interface RetreivedDoc {
  doc_id: string
  chunk_id: string
  text: string
  score: number
}

export interface QAResponse {
  query: string
  answer: string
  query_type: string
  confidence: number
  citations: string[]
  graph_context: string
  retrieved_docs: RetreivedDoc[]
  validation: Record<string, unknown>
  processing_time_ms: number
}

export interface DocumentInfo {
  doc_id: string
  filename: string
  folder: string
  tags: string[]
  status: string
  processing_stage: string
  chunk_count: number
  processing_time_ms: number
  error?: string
  created_at: string
  updated_at: string
}

export interface FolderInfo {
  folder: string
  doc_count: number
}

export interface TagInfo {
  tag: string
  count: number
}

export interface DocumentStatus {
  doc_id: string
  status: string
  processing_stage: string
  chunk_count: number
  processing_time_ms: number
  error?: string
}

export interface SystemStats {
  document_count: number
  chunk_count: number
  milvus_vector_count: number
  neo4j_entity_count: number
  neo4j_relation_count: number
}

// ── Documents ──

export async function uploadDocument(file: File, folder: string = '/'): Promise<{ doc_id: string; filename: string; folder: string; status: string }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('folder', folder)
  const res = await fetch(`${API_BASE}/documents/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
  return res.json()
}

export async function getDocumentStatus(docId: string): Promise<DocumentStatus> {
  const res = await fetch(`${API_BASE}/documents/status/${docId}`)
  if (!res.ok) throw new Error(`Status check failed: ${res.statusText}`)
  return res.json()
}

export async function listDocuments(folder?: string, tags?: string[], status?: string): Promise<DocumentInfo[]> {
  const params = new URLSearchParams()
  if (folder) params.set('folder', folder)
  if (tags?.length) params.set('tags', tags.join(','))
  if (status) params.set('status', status)
  const res = await fetch(`${API_BASE}/documents/list?${params}`)
  if (!res.ok) throw new Error(`List failed: ${res.statusText}`)
  return res.json()
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete failed: ${res.statusText}`)
}

export async function moveDocument(docId: string, folder: string): Promise<DocumentInfo> {
  const res = await fetch(`${API_BASE}/documents/${docId}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder }),
  })
  if (!res.ok) throw new Error(`Move failed: ${res.statusText}`)
  return res.json()
}

export async function addTag(docId: string, tag: string): Promise<DocumentInfo> {
  const res = await fetch(`${API_BASE}/documents/${docId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag }),
  })
  if (!res.ok) throw new Error(`Add tag failed: ${res.statusText}`)
  return res.json()
}

export interface DocumentContent {
  doc_id: string
  filename: string
  original_content: string
  parsed_markdown: string
  raw_url: string
  is_binary: boolean
  file_ext: string
  file_size_kb: number
  status: string
}

export async function getDocumentContent(docId: string): Promise<DocumentContent> {
  const res = await fetch(`${API_BASE}/documents/${docId}/content`)
  if (!res.ok) throw new Error(`Get content failed: ${res.statusText}`)
  return res.json()
}

export async function retryDocument(docId: string): Promise<{ doc_id: string; filename: string; folder: string; status: string }> {
  const res = await fetch(`${API_BASE}/documents/${docId}/retry`, { method: 'POST' })
  if (!res.ok) throw new Error(`Retry failed: ${res.statusText}`)
  return res.json()
}

export async function removeTag(docId: string, tag: string): Promise<DocumentInfo> {
  const res = await fetch(`${API_BASE}/documents/${docId}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Remove tag failed: ${res.statusText}`)
  return res.json()
}

// ── Folders & Tags ──

export async function listFolders(): Promise<FolderInfo[]> {
  const res = await fetch(`${API_BASE}/documents/folders`)
  if (!res.ok) throw new Error(`List folders failed: ${res.statusText}`)
  return res.json()
}

export async function listTags(): Promise<TagInfo[]> {
  const res = await fetch(`${API_BASE}/documents/tags`)
  if (!res.ok) throw new Error(`List tags failed: ${res.statusText}`)
  return res.json()
}

// ── QA ──

export async function askQuestion(query: string, folder?: string, tags?: string[]): Promise<QAResponse> {
  const res = await fetch(`${API_BASE}/qa/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, stream: false, folder, tags }),
  })
  if (!res.ok) throw new Error(`QA failed: ${res.statusText}`)
  return res.json()
}

export interface StreamStep {
  type: string
  node: string
  label: string
  detail: string
  status: string
  error?: string
  result?: Record<string, unknown>
}

export async function askQuestionStream(
  query: string,
  onStep: (step: StreamStep) => void,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string) => void,
  folder?: string,
  tags?: string[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/qa/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, stream: true, folder, tags }),
  })
  if (!res.ok) {
    onError(`Stream failed: ${res.statusText}`)
    return
  }
  const reader = res.body?.getReader()
  if (!reader) {
    onError('No response body')
    return
  }
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        try {
          const parsed = JSON.parse(data)
          if (parsed.type === 'done') {
            onDone(parsed)
            return
          }
          if (parsed.type === 'error') {
            onError(parsed.error || 'Unknown error')
            return
          }
          if (parsed.type === 'step') {
            onStep(parsed as StreamStep)
          }
        } catch {
          // skip malformed
        }
      }
    }
  }
  onDone({})
}

// ── System ──

export async function getSystemStats(): Promise<SystemStats> {
  const res = await fetch(`${API_BASE}/system/stats`)
  if (!res.ok) throw new Error(`Stats failed: ${res.statusText}`)
  return res.json()
}

export interface ConfigCategory {
  category: string
  items: { key: string; label: string; value: string }[]
}

export interface ConfigResponse {
  categories: ConfigCategory[]
  secrets: Record<string, string>
}

export async function getConfig(): Promise<ConfigResponse> {
  const res = await fetch(`${API_BASE}/system/config`)
  if (!res.ok) throw new Error(`Config failed: ${res.statusText}`)
  return res.json()
}

export interface ConnectivityResult {
  service: string
  status: string
  detail: string
  latency_ms: number
}

export async function checkConnectivity(): Promise<ConnectivityResult[]> {
  const res = await fetch(`${API_BASE}/system/connectivity-check`)
  if (!res.ok) throw new Error(`Connectivity check failed: ${res.statusText}`)
  return res.json()
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch('/health')
    return res.ok
  } catch {
    return false
  }
}
