const API_BASE = '/api/v1'

export interface RetrievedDoc {
  doc_id: string
  chunk_id: string
  text: string
  score: number
  rerank_score?: number | null
  dense_score?: number | null
  bm25_score?: number | null
  filename?: string
}

export interface QAResponse {
  query: string
  answer: string
  query_type: string
  confidence: number
  citations: string[]
  graph_context: string
  retrieved_docs: RetrievedDoc[]
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

export interface ChunkInfo {
  chunk_id: string
  text: string
  heading: string
  metadata: Record<string, unknown>
}

export interface DocumentChunks {
  doc_id: string
  chunks: ChunkInfo[]
  total: number
}

export interface GraphNode {
  id: string
  label: string
  type: string
  doc_id: string
  description: string
}

export interface GraphEdge {
  source: string
  target: string
  type: string
}

export interface GraphOverview {
  nodes: GraphNode[]
  edges: GraphEdge[]
  total_nodes: number
  total_edges: number
}

// ── Documents ──

export async function uploadDocument(file: File, folder: string = '/', skipEvidence: boolean = false): Promise<{ doc_id: string; filename: string; folder: string; status: string }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('folder', folder)
  if (skipEvidence) formData.append('skip_evidence', 'true')
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

export async function getDocumentChunks(docId: string): Promise<DocumentChunks> {
  const res = await fetch(`${API_BASE}/documents/${docId}/chunks`)
  if (!res.ok) throw new Error(`Get chunks failed: ${res.statusText}`)
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

// ── Folder Management ──

export async function createFolder(path: string): Promise<{ folder: string; doc_count: number }> {
  const res = await fetch(`${API_BASE}/documents/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) throw new Error(`Create folder failed: ${res.statusText}`)
  return res.json()
}

export async function deleteFolder(path: string): Promise<{ deleted: boolean; folder: string; doc_count: number }> {
  const res = await fetch(`${API_BASE}/documents/folders${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete folder failed: ${res.statusText}`)
  return res.json()
}

export async function moveFolder(src: string, dst: string): Promise<{ moved: boolean; src: string; dst: string; doc_count: number }> {
  const res = await fetch(`${API_BASE}/documents/folders/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src, dst }),
  })
  if (!res.ok) throw new Error(`Move folder failed: ${res.statusText}`)
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

export async function getGraphOverview(docId?: string): Promise<GraphOverview> {
  const params = docId ? `?doc_id=${encodeURIComponent(docId)}` : ''
  const res = await fetch(`${API_BASE}/system/graph/overview${params}`)
  if (!res.ok) throw new Error(`Graph overview failed: ${res.statusText}`)
  return res.json()
}

export interface EntityDetail {
  name: string
  type: string
  description: string
  doc_id: string
  documents: Array<{
    doc_id: string
    filename: string
    folder: string
    status: string
    chunk_count: number
    [key: string]: unknown
  }>
  related_chunks: ChunkInfo[]
}

export async function getEntityDetail(entityName: string): Promise<EntityDetail> {
  const res = await fetch(`${API_BASE}/system/graph/entity/${encodeURIComponent(entityName)}`)
  if (!res.ok) throw new Error(`Entity detail failed: ${res.statusText}`)
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

// ── Search Debug ──

export interface SearchDebugChunk {
  chunk_id: string
  doc_id: string
  filename: string
  text_preview: string
  score?: number
  rrf_raw?: number
  rrf_normalized?: number
  rrf_pass_threshold?: boolean
  dense_score?: number
  bm25_score?: number
  rerank_score?: number
  rerank_pass_threshold?: boolean
}

export interface SearchDebugResponse {
  query: string
  threshold: number
  rrf_threshold: number
  dense_threshold: number
  rerank_threshold: number
  rewrite: {
    original: string
    dense_query: string
    bm25_query: string
    dense_tokens: string[]
    bm25_tokens: string[]
    query_tokens: string[]
    enabled: boolean
  }
  stages: {
    dense_top5: SearchDebugChunk[]
    bm25_top5: SearchDebugChunk[]
    rrf: SearchDebugChunk[]
    rerank: SearchDebugChunk[]
  }
  final_count: number
  filtered_out_by_rerank_threshold: number
  message?: string
}

export async function searchDebug(query: string, folder?: string | null, tags?: string[], docId?: string | null, topK?: number): Promise<SearchDebugResponse> {
  const res = await fetch(`${API_BASE}/system/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, folder: folder || undefined, tags: tags?.length ? tags : undefined, doc_id: docId || undefined, top_k: topK || 20 }),
  })
  if (!res.ok) throw new Error(`Search debug failed: ${res.statusText}`)
  return res.json()
}

// ── Config Overrides ──

export interface EditableConfigItem {
  key: string
  value: string
  overridden: boolean
}

export interface ConfigSchema {
  type: 'string' | 'int' | 'float' | 'bool' | 'enum'
  label: string
  min?: number
  max?: number
  options?: string[]
}

export const CONFIG_SCHEMA: Record<string, ConfigSchema> = {
  retrieval_similarity_threshold: { type: 'float', label: '相似度阈值', min: 0, max: 1 },
  rrf_score_threshold: { type: 'float', label: 'RRF 分数阈值', min: 0, max: 1 },
  dense_vector_threshold: { type: 'float', label: 'Dense 向量阈值', min: 0, max: 1 },
  reranker_score_threshold: { type: 'float', label: 'Rerank 阈值', min: 0, max: 1 },
  reranker_method: { type: 'enum', label: 'Rerank 方法', options: ['embedding', 'llm', 'hybrid'] },
  chunk_size: { type: 'int', label: '分块大小', min: 64, max: 4096 },
  chunk_overlap: { type: 'int', label: '分块重叠', min: 0, max: 2048 },
  hybrid_top_k: { type: 'int', label: '混合检索 Top-K', min: 1, max: 100 },
  hybrid_dense_weight: { type: 'float', label: 'Dense 权重', min: 0, max: 1 },
  hybrid_bm25_weight: { type: 'float', label: 'BM25 权重', min: 0, max: 1 },
  hybrid_rrf_k: { type: 'int', label: 'RRF k 值', min: 1, max: 200 },
  agent_max_iterations: { type: 'int', label: '验证最大轮次', min: 1, max: 10 },
  agent_temperature: { type: 'float', label: 'LLM 温度', min: 0, max: 2 },
  query_rewrite_enabled: { type: 'bool', label: '查询改写开关' },
  query_rewrite_language: { type: 'string', label: '改写语言' },
}

export function validateConfigValue(key: string, value: string): string | null {
  const schema = CONFIG_SCHEMA[key]
  if (!schema) return null

  if (schema.type === 'bool') {
    const v = value.toLowerCase()
    if (v !== 'true' && v !== 'false' && v !== '0' && v !== '1') return '请输入 true 或 false'
    return null
  }
  if (schema.type === 'int') {
    const v = parseInt(value)
    if (isNaN(v)) return '请输入整数'
    if (schema.min !== undefined && v < schema.min) return `最小值为 ${schema.min}`
    if (schema.max !== undefined && v > schema.max) return `最大值为 ${schema.max}`
    return null
  }
  if (schema.type === 'float') {
    const v = parseFloat(value)
    if (isNaN(v)) return '请输入数字'
    if (schema.min !== undefined && v < schema.min) return `最小值为 ${schema.min}`
    if (schema.max !== undefined && v > schema.max) return `最大值为 ${schema.max}`
    return null
  }
  if (schema.type === 'enum' && schema.options) {
    if (!schema.options.includes(value)) return `可选值: ${schema.options.join(', ')}`
    return null
  }
  return null
}

export async function listEditableConfig(): Promise<EditableConfigItem[]> {
  const res = await fetch(`${API_BASE}/system/config/editable`)
  if (!res.ok) throw new Error(`List editable config failed: ${res.statusText}`)
  return res.json()
}

export async function updateConfigOverride(key: string, value: string): Promise<{ key: string; value: unknown; saved: boolean }> {
  const res = await fetch(`${API_BASE}/system/config/editable`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  })
  if (!res.ok) throw new Error(`Update config failed: ${res.statusText}`)
  return res.json()
}

export async function resetConfigOverride(key: string): Promise<void> {
  const res = await fetch(`${API_BASE}/system/config/editable/${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Reset config failed: ${res.statusText}`)
}

export async function cleanupOrphans(): Promise<{ milvus_deleted: number; neo4j_deleted_entities: number }> {
  const res = await fetch(`${API_BASE}/system/cleanup-orphans`, { method: 'POST' })
  if (!res.ok) throw new Error(`Cleanup failed: ${res.statusText}`)
  return res.json()
}

export interface BuildGraphResult {
  success: boolean
  message?: string
  status?: { running: boolean; progress: number; total: number; done: boolean; result?: Record<string, unknown> }
  chunks_processed?: number
  evidence_count?: number
  affected_keys?: number
  sync_success?: number
  sync_failed?: number
  errors?: number
}

export async function buildGraph(): Promise<BuildGraphResult> {
  const res = await fetch(`${API_BASE}/system/build-graph`, { method: 'POST' })
  if (!res.ok) throw new Error(`Build graph failed: ${res.statusText}`)
  return res.json()
}

export async function buildGraphStatus(): Promise<BuildGraphResult['status'] & { result?: BuildGraphResult; phase?: string }> {
  const res = await fetch(`${API_BASE}/system/build-graph/status`)
  if (!res.ok) throw new Error(`Status check failed: ${res.statusText}`)
  return res.json()
}

export async function deleteAllVectors(): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${API_BASE}/system/delete-all-vectors`, { method: 'POST' })
  if (!res.ok) throw new Error(`Delete vectors failed: ${res.statusText}`)
  return res.json()
}

export async function rebuildBM25(): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${API_BASE}/system/rebuild-bm25`, { method: 'POST' })
  if (!res.ok) throw new Error(`Rebuild BM25 failed: ${res.statusText}`)
  return res.json()
}

export async function deleteAllGraph(): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${API_BASE}/system/delete-all-graph`, { method: 'POST' })
  if (!res.ok) throw new Error(`Delete graph failed: ${res.statusText}`)
  return res.json()
}

export async function deleteInactiveGraph(): Promise<{ success: boolean; entities_deleted?: number; facts_deleted?: number; attrs_deleted?: number; message?: string }> {
  const res = await fetch(`${API_BASE}/system/delete-inactive-graph`, { method: 'POST' })
  if (!res.ok) throw new Error(`Delete inactive graph failed: ${res.statusText}`)
  return res.json()
}

// ── Evaluation ──

export interface EvalSample {
  id: string
  query: string
  query_type: string
  ground_truth_answer: string
  ground_truth_sources: string[]
  ground_truth_ids: string[]
}

export interface EvalResultSummary {
  filename: string
  timestamp: number
  num_samples: number
  // P1: Core
  context_relevancy: number
  context_recall: number
  answer_relevancy: number
  faithfulness: number
  // P1: Precision & NDCG
  precision_at_5: number | null
  precision_at_10: number | null
  ndcg_at_5: number | null
  // P1: Hallucination
  intrinsic_hallucination_rate: number
  extrinsic_hallucination_rate: number
  // P1: Completeness
  answer_completeness: number
  // P2
  mrr: number | null
  context_redundancy: number
  delta_ndcg: number | null
  filter_drop_rate: number
  // P3
  timing_mean_ms: number
  timing_p95_ms: number
  // legacy
  recall_at_5: number
  recall_at_10: number
  semantic_similarity: number
  judge_accuracy: number
  citation_accuracy: number
}

export interface EvalSampleResult {
  sample_id: string
  query: string
  query_type: string
  predicted_answer: string
  cited_sources: string[]
  retrieved_ids: string[]
  retrieved_texts: string[]
  error?: string
  processing_time_ms: number
}

export interface EvalResultDetail {
  summary: {
    num_samples: number
    context_relevancy: number
    context_recall: number
    answer_relevancy: number
    faithfulness: number
    precision_at_5: number | null
    precision_at_10: number | null
    ndcg_at_5: number | null
    intrinsic_hallucination_rate: number
    extrinsic_hallucination_rate: number
    answer_completeness: number
    mrr: number | null
    context_redundancy: number
    delta_ndcg: number | null
    filter_drop_rate: number
    timing_mean_ms: number
    timing_p95_ms: number
    recall_at_5: number
    recall_at_10: number
    semantic_similarity: number
    judge_accuracy: number
    citation_accuracy: number
  }
  total_time_seconds: number
  avg_time_per_sample: number
  results: EvalSampleResult[]
}

export async function listDataset(): Promise<EvalSample[]> {
  const res = await fetch(`${API_BASE}/evaluation/dataset`)
  if (!res.ok) throw new Error(`List dataset failed: ${res.statusText}`)
  return res.json()
}

export async function addSample(sample: Omit<EvalSample, 'id'> & { id?: string }): Promise<EvalSample> {
  const res = await fetch(`${API_BASE}/evaluation/dataset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sample),
  })
  if (!res.ok) throw new Error(`Add sample failed: ${res.statusText}`)
  return res.json()
}

export async function updateSample(sampleId: string, updates: Partial<EvalSample>): Promise<EvalSample> {
  const res = await fetch(`${API_BASE}/evaluation/dataset/${encodeURIComponent(sampleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`Update sample failed: ${res.statusText}`)
  return res.json()
}

export async function deleteSample(sampleId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/evaluation/dataset/${encodeURIComponent(sampleId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`Delete sample failed: ${res.statusText}`)
}

export async function importDataset(samples: Record<string, unknown>[], mode: 'replace' | 'merge' = 'replace'): Promise<{ count: number; mode: string }> {
  const res = await fetch(`${API_BASE}/evaluation/dataset/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ samples, mode }),
  })
  if (!res.ok) throw new Error(`Import dataset failed: ${res.statusText}`)
  return res.json()
}

export async function exportDataset(): Promise<EvalSample[]> {
  const res = await fetch(`${API_BASE}/evaluation/dataset/export`)
  if (!res.ok) throw new Error(`Export dataset failed: ${res.statusText}`)
  return res.json()
}

export interface EvalProgressEvent {
  type: 'start' | 'progress' | 'sample_done' | 'done'
  total?: number
  current?: number
  sample_id?: string
  query?: string
  processing_time_ms?: number
  error?: string
  summary?: Record<string, number>
  filename?: string
}

export async function runEvaluation(
  maxSamples: number | null,
  folder: string | null,
  onEvent: (evt: EvalProgressEvent) => void,
  onDone: (summary: Record<string, number>, filename: string) => void,
  onError: (err: string) => void,
): Promise<void> {
  const body: Record<string, unknown> = { max_samples: maxSamples || undefined }
  if (folder) body.folder = folder
  const res = await fetch(`${API_BASE}/evaluation/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const msg = `HTTP ${res.status}: ${res.statusText || 'Unknown error'}`
    try { const b = await res.json(); onError(b?.detail || b?.error || msg) } catch { onError(msg) }
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
          const parsed = JSON.parse(data) as EvalProgressEvent
          if (parsed.type === 'done') {
            onDone(parsed.summary || {}, parsed.filename || '')
            return
          }
          onEvent(parsed)
        } catch {
          // skip malformed
        }
      }
    }
  }
  onDone({}, '')
}

export async function listResults(): Promise<EvalResultSummary[]> {
  const res = await fetch(`${API_BASE}/evaluation/results`)
  if (!res.ok) throw new Error(`List results failed: ${res.statusText}`)
  return res.json()
}

export async function getResult(filename: string): Promise<EvalResultDetail> {
  const res = await fetch(`${API_BASE}/evaluation/results/${encodeURIComponent(filename)}`)
  if (!res.ok) throw new Error(`Get result failed: ${res.statusText}`)
  return res.json()
}

export async function deleteResult(filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}/evaluation/results/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`Delete result failed: ${res.statusText}`)
}

export interface GenerateProgressEvent {
  type: 'start' | 'progress' | 'sample_generated' | 'done' | 'error'
  total?: number
  current?: number
  folder?: string
  doc_id?: string
  sample_id?: string
  query?: string
  count?: number
  mode?: string
  error?: string
  warning?: string
}

export async function generateDataset(
  folder: string | null,
  maxDocs: number,
  samplesPerDoc: number,
  mode: 'replace' | 'merge',
  onEvent: (evt: GenerateProgressEvent) => void,
  onDone: (count: number) => void,
  onError: (err: string) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/evaluation/dataset/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder: folder || '/', max_docs: maxDocs, samples_per_doc: samplesPerDoc, mode }),
  })
  if (!res.ok) {
    const msg = `HTTP ${res.status}: ${res.statusText || 'Unknown error'}`
    try { const b = await res.json(); onError(b?.detail || b?.error || msg) } catch { onError(msg) }
    return
  }
  const reader = res.body?.getReader()
  if (!reader) { onError('No response body'); return }
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
          const parsed = JSON.parse(data) as GenerateProgressEvent
          if (parsed.type === 'error') { onError(parsed.error || 'Unknown error'); return }
          if (parsed.type === 'done') { onDone(parsed.count || 0); return }
          onEvent(parsed)
        } catch { /* skip malformed */ }
      }
    }
  }
  onDone(0)
}
