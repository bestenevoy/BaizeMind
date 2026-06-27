const API_BASE = '/api/v1'

// ── Auth token 管理 ──
const AUTH_TOKEN_KEY = 'agentic_rag_auth_token'

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null) {
  try {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
    else localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

/** 统一的 fetch 封装：自动注入 Authorization header，并在 401 时清除 token。 */
async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getAuthToken()
  const headers = new Headers(init.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(input, { ...init, headers })
  if (res.status === 401) {
    // 仅清除 token，由调用方/上层决定如何提示用户登录
    setAuthToken(null)
  }
  return res
}

export interface SheetColumn {
  cn?: string
  en: string
  type: string
}

export interface RetrievedDoc {
  doc_id: string
  chunk_id: string
  text: string
  score: number
  rerank_score?: number | null
  dense_score?: number | null
  bm25_score?: number | null
  filename?: string
  sheet_name?: string
  source_type?: string
  // sql_agent 命中路径：SQL 执行结果
  sql_result_columns?: string[]
  sql_result_rows?: unknown[][]
  sql_result_row_count?: number
  // sheet_summary doc：sheet 元数据（行数/列结构）
  sheet_row_count?: number
  sheet_columns?: SheetColumn[]
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
  file_type: string
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
  const res = await authFetch(`${API_BASE}/documents/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
  return res.json()
}

export async function getDocumentStatus(docId: string): Promise<DocumentStatus> {
  const res = await authFetch(`${API_BASE}/documents/status/${docId}`)
  if (!res.ok) throw new Error(`Status check failed: ${res.statusText}`)
  return res.json()
}

export async function listDocuments(folder?: string, tags?: string[], status?: string, fileType?: string): Promise<DocumentInfo[]> {
  const params = new URLSearchParams()
  if (folder) params.set('folder', folder)
  if (tags?.length) params.set('tags', tags.join(','))
  if (status) params.set('status', status)
  if (fileType) params.set('file_type', fileType)
  const res = await authFetch(`${API_BASE}/documents/list?${params}`)
  if (!res.ok) throw new Error(`List failed: ${res.statusText}`)
  return res.json()
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/documents/${docId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete failed: ${res.statusText}`)
}

export async function moveDocument(docId: string, folder: string): Promise<DocumentInfo> {
  const res = await authFetch(`${API_BASE}/documents/${docId}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder }),
  })
  if (!res.ok) throw new Error(`Move failed: ${res.statusText}`)
  return res.json()
}

export async function addTag(docId: string, tag: string): Promise<DocumentInfo> {
  const res = await authFetch(`${API_BASE}/documents/${docId}/tags`, {
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
  const res = await authFetch(`${API_BASE}/documents/${docId}/content`)
  if (!res.ok) throw new Error(`Get content failed: ${res.statusText}`)
  return res.json()
}

export async function getDocumentChunks(docId: string): Promise<DocumentChunks> {
  const res = await authFetch(`${API_BASE}/documents/${docId}/chunks`)
  if (!res.ok) throw new Error(`Get chunks failed: ${res.statusText}`)
  return res.json()
}

export async function retryDocument(docId: string): Promise<{ doc_id: string; filename: string; folder: string; status: string }> {
  const res = await authFetch(`${API_BASE}/documents/${docId}/retry`, { method: 'POST' })
  if (!res.ok) throw new Error(`Retry failed: ${res.statusText}`)
  return res.json()
}

export async function removeTag(docId: string, tag: string): Promise<DocumentInfo> {
  const res = await authFetch(`${API_BASE}/documents/${docId}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Remove tag failed: ${res.statusText}`)
  return res.json()
}

// ── Folder Management ──

export async function createFolder(path: string): Promise<{ folder: string; doc_count: number }> {
  const res = await authFetch(`${API_BASE}/documents/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) throw new Error(`Create folder failed: ${res.statusText}`)
  return res.json()
}

export async function deleteFolder(path: string): Promise<{ deleted: boolean; folder: string; doc_count: number }> {
  const res = await authFetch(`${API_BASE}/documents/folders${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete folder failed: ${res.statusText}`)
  return res.json()
}

export async function moveFolder(src: string, dst: string): Promise<{ moved: boolean; src: string; dst: string; doc_count: number }> {
  const res = await authFetch(`${API_BASE}/documents/folders/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src, dst }),
  })
  if (!res.ok) throw new Error(`Move folder failed: ${res.statusText}`)
  return res.json()
}

// ── Folders & Tags ──

export async function listFolders(): Promise<FolderInfo[]> {
  const res = await authFetch(`${API_BASE}/documents/folders`)
  if (!res.ok) throw new Error(`List folders failed: ${res.statusText}`)
  return res.json()
}

export async function listTags(): Promise<TagInfo[]> {
  const res = await authFetch(`${API_BASE}/documents/tags`)
  if (!res.ok) throw new Error(`List tags failed: ${res.statusText}`)
  return res.json()
}

// ── QA ──

export async function askQuestion(
  query: string,
  folder?: string,
  tags?: string[],
  docIds?: string[],
): Promise<QAResponse> {
  const res = await authFetch(`${API_BASE}/qa/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, stream: false, folder, tags, doc_ids: docIds }),
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
  docIds?: string[],
): Promise<void> {
  const res = await authFetch(`${API_BASE}/qa/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, stream: true, folder, tags, doc_ids: docIds }),
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
  const res = await authFetch(`${API_BASE}/system/stats`)
  if (!res.ok) throw new Error(`Stats failed: ${res.statusText}`)
  return res.json()
}

export async function getGraphOverview(docId?: string): Promise<GraphOverview> {
  const params = docId ? `?doc_id=${encodeURIComponent(docId)}` : ''
  const res = await authFetch(`${API_BASE}/system/graph/overview${params}`)
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
  const res = await authFetch(`${API_BASE}/system/graph/entity/${encodeURIComponent(entityName)}`)
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
  const res = await authFetch(`${API_BASE}/system/config`)
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
  const res = await authFetch(`${API_BASE}/system/connectivity-check`)
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
  dense_score?: number
  bm25_score?: number
  rerank_score?: number
  rerank_pass_threshold?: boolean
  source_queries?: number[]
}

export interface DenseQueryInfo {
  index: number
  dense_query: string
  dense_tokens: string[]
  query_tokens: string[]
}

export interface PerQueryStage {
  index: number
  dense_query: string
  dense_top: SearchDebugChunk[]
  dense_count: number
}

export interface SqlRecalledSheet {
  meta_id: string
  doc_id: string
  sheet_name: string
  score: number
  summary: string
  selected: boolean
}

export interface SqlDebugSelectedSheet {
  meta_id: string
  doc_id: string
  sheet_name: string
  score: number
  columns: Array<{ cn?: string; en: string; type: string }>
  row_count: number
  summary: string
}

export interface SqlDebugAttempt {
  attempt: number
  sql?: string
  error?: string
  valid?: boolean
  row_count?: number
}

export interface SqlDebug {
  recalled_sheets: SqlRecalledSheet[]
  selected_sheet: SqlDebugSelectedSheet | null
  sql: string
  sql_result_columns: string[]
  sql_result_rows: unknown[][]
  sql_result_row_count: number
  attempts: SqlDebugAttempt[]
  error: string
  fallback_reason: string
}

export interface SearchDebugResponse {
  query: string
  query_type?: string  // "simple_fact" | "multi_hop" | "comparison" | "definition" | "holistic" | "chitchat"
  multi_query?: boolean
  query_count?: number
  dense_union_count?: number
  threshold: number
  dense_threshold: number
  rerank_threshold: number
  rrf_k: number
  over_fetch_multiplier: number
  top_k: number
  rerank_top_k: number
  rewrite: {
    original: string
    dense_query: string
    bm25_query: string
    dense_tokens: string[]
    bm25_tokens: string[]
    query_tokens: string[]
    enabled: boolean
    dense_queries?: DenseQueryInfo[]
  }
  stages: {
    per_query?: PerQueryStage[]
    dense_top5: SearchDebugChunk[]
    bm25_top5: SearchDebugChunk[]
    rrf: SearchDebugChunk[]
    rerank: SearchDebugChunk[]
  }
  source_queries?: Record<string, number[]>
  final_count: number
  filtered_out_by_rerank_threshold: number
  message?: string
  sql_debug?: SqlDebug  // 仅 SearchDebugPanel 强制 forcePath="sql" 时存在（debug 端点专属，非主工作流路径）
}

export async function searchDebug(
  query: string,
  folder?: string | null,
  tags?: string[],
  docId?: string | null,
  topK?: number,
  forcePath?: 'auto' | 'doc' | 'sql',
): Promise<SearchDebugResponse> {
  const res = await authFetch(`${API_BASE}/system/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // top_k 不传时后端用 settings.hybrid_top_k（可被 runtime 页编辑覆盖）
    body: JSON.stringify({
      query,
      folder: folder || undefined,
      tags: tags?.length ? tags : undefined,
      doc_id: docId || undefined,
      ...(topK ? { top_k: topK } : {}),
      force_path: forcePath || 'auto',
    }),
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
  description?: string
}

export const CONFIG_SCHEMA: Record<string, ConfigSchema> = {
  dense_vector_threshold: { type: 'float', label: '稠密向量阈值', min: 0, max: 1 },
  reranker_score_threshold: { type: 'float', label: 'Rerank 分数阈值', min: 0, max: 1 },
  reranker_method: { type: 'enum', label: 'Rerank 方法', options: ['embedding', 'llm', 'hybrid'] },
  chunk_size: { type: 'int', label: '分块大小', min: 64, max: 4096 },
  chunk_overlap: { type: 'int', label: '分块重叠', min: 0, max: 2048 },
  hybrid_top_k: { type: 'int', label: 'RRF Top-K', min: 1, max: 100 },
  hybrid_dense_weight: { type: 'float', label: 'Dense 权重', min: 0, max: 1 },
  hybrid_bm25_weight: { type: 'float', label: 'BM25 权重', min: 0, max: 1 },
  hybrid_rrf_k: { type: 'int', label: 'RRF 平滑常数', min: 1, max: 200 },
  retrieval_over_fetch_multiplier: { type: 'int', label: '预取倍数', min: 1, max: 10 },
  rerank_top_k: { type: 'int', label: 'Rerank 输出数', min: 1, max: 100 },
  agent_max_iterations: { type: 'int', label: '验证最大轮次', min: 1, max: 10 },
  agent_temperature: { type: 'float', label: 'LLM 温度', min: 0, max: 2 },
  query_rewrite_enabled: { type: 'bool', label: '查询改写开关' },
  response_language: { type: 'string', label: '响应语言' },
  query_rewrite_count: { type: 'int', label: '改写 Query 数量', min: 1, max: 8 },
  parser_backend: { type: 'enum', label: '默认解析器', options: ['mineru', 'paddleocr_vl'] },
  auth_guest_chat_max_length: { type: 'int', label: '访客单次查询字数上限', min: 0, max: 10000, description: '0 表示不限制；同时作用于 chat 与检索测试' },
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
  const res = await authFetch(`${API_BASE}/system/config/editable`)
  if (!res.ok) throw new Error(`List editable config failed: ${res.statusText}`)
  return res.json()
}

export async function updateConfigOverride(key: string, value: string): Promise<{ key: string; value: unknown; saved: boolean }> {
  const res = await authFetch(`${API_BASE}/system/config/editable`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  })
  if (!res.ok) throw new Error(`Update config failed: ${res.statusText}`)
  return res.json()
}

export async function resetConfigOverride(key: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/system/config/editable/${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Reset config failed: ${res.statusText}`)
}

// ── Cache Management ──

export interface CacheEntry {
  key: string
  namespace: string
  value_preview: string
  value_length: number
  input_preview: string
  input_length: number
  has_full_input: boolean
  caller: string
  created_at: number
  expires_at: number | null
  ttl_remaining: number | null
}

export interface CacheEntryDetail {
  enabled: boolean
  key: string
  namespace: string
  content: string
  content_length: number
  input: string
  input_length: number
  caller: string
  created_at: number
  expires_at: number | null
  ttl_remaining: number | null
  message?: string
}

export interface CacheListResponse {
  enabled: boolean
  backend: string
  ttl_seconds: number
  total: number
  filtered_total: number
  filtered_prefix?: string | null
  namespaces?: Record<string, number>
  entries: CacheEntry[]
  message?: string
}

export async function listCache(prefix?: string): Promise<CacheListResponse> {
  const params = prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''
  const res = await authFetch(`${API_BASE}/system/cache${params}`)
  if (!res.ok) throw new Error(`List cache failed: ${res.statusText}`)
  return res.json()
}

export async function clearCache(prefix?: string): Promise<{ success: boolean; cleared: number; prefix: string | null; message?: string }> {
  const params = prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''
  const res = await authFetch(`${API_BASE}/system/cache/clear${params}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Clear cache failed: ${res.statusText}`)
  return res.json()
}

export async function deleteCacheEntry(key: string): Promise<{ success: boolean; existed: boolean; key: string }> {
  const res = await authFetch(`${API_BASE}/system/cache/${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete cache entry failed: ${res.statusText}`)
  return res.json()
}

export async function getCacheEntry(key: string): Promise<CacheEntryDetail> {
  const res = await authFetch(`${API_BASE}/system/cache/${encodeURIComponent(key)}`)
  if (!res.ok) throw new Error(`Get cache entry failed: ${res.statusText}`)
  return res.json()
}

export async function cleanupOrphans(): Promise<{ milvus_deleted: number; neo4j_deleted_entities: number }> {
  const res = await authFetch(`${API_BASE}/system/cleanup-orphans`, { method: 'POST' })
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
  const res = await authFetch(`${API_BASE}/system/build-graph`, { method: 'POST' })
  if (!res.ok) throw new Error(`Build graph failed: ${res.statusText}`)
  return res.json()
}

export async function buildGraphStatus(): Promise<BuildGraphResult['status'] & { result?: BuildGraphResult; phase?: string }> {
  const res = await authFetch(`${API_BASE}/system/build-graph/status`)
  if (!res.ok) throw new Error(`Status check failed: ${res.statusText}`)
  return res.json()
}

export async function deleteAllVectors(): Promise<{ success: boolean; message?: string }> {
  const res = await authFetch(`${API_BASE}/system/delete-all-vectors`, { method: 'POST' })
  if (!res.ok) throw new Error(`Delete vectors failed: ${res.statusText}`)
  return res.json()
}

export async function rebuildBM25(): Promise<{ success: boolean; message?: string }> {
  const res = await authFetch(`${API_BASE}/system/rebuild-bm25`, { method: 'POST' })
  if (!res.ok) throw new Error(`Rebuild BM25 failed: ${res.statusText}`)
  return res.json()
}

export async function deleteAllGraph(): Promise<{ success: boolean; message?: string }> {
  const res = await authFetch(`${API_BASE}/system/delete-all-graph`, { method: 'POST' })
  if (!res.ok) throw new Error(`Delete graph failed: ${res.statusText}`)
  return res.json()
}

export async function deleteInactiveGraph(): Promise<{ success: boolean; entities_deleted?: number; facts_deleted?: number; attrs_deleted?: number; message?: string }> {
  const res = await authFetch(`${API_BASE}/system/delete-inactive-graph`, { method: 'POST' })
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
  const res = await authFetch(`${API_BASE}/evaluation/dataset`)
  if (!res.ok) throw new Error(`List dataset failed: ${res.statusText}`)
  return res.json()
}

export async function addSample(sample: Omit<EvalSample, 'id'> & { id?: string }): Promise<EvalSample> {
  const res = await authFetch(`${API_BASE}/evaluation/dataset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sample),
  })
  if (!res.ok) throw new Error(`Add sample failed: ${res.statusText}`)
  return res.json()
}

export async function updateSample(sampleId: string, updates: Partial<EvalSample>): Promise<EvalSample> {
  const res = await authFetch(`${API_BASE}/evaluation/dataset/${encodeURIComponent(sampleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`Update sample failed: ${res.statusText}`)
  return res.json()
}

export async function deleteSample(sampleId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/evaluation/dataset/${encodeURIComponent(sampleId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`Delete sample failed: ${res.statusText}`)
}

export async function importDataset(samples: Record<string, unknown>[], mode: 'replace' | 'merge' = 'replace'): Promise<{ count: number; mode: string }> {
  const res = await authFetch(`${API_BASE}/evaluation/dataset/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ samples, mode }),
  })
  if (!res.ok) throw new Error(`Import dataset failed: ${res.statusText}`)
  return res.json()
}

export async function exportDataset(): Promise<EvalSample[]> {
  const res = await authFetch(`${API_BASE}/evaluation/dataset/export`)
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
  const res = await authFetch(`${API_BASE}/evaluation/run`, {
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
  const res = await authFetch(`${API_BASE}/evaluation/results`)
  if (!res.ok) throw new Error(`List results failed: ${res.statusText}`)
  return res.json()
}

export async function getResult(filename: string): Promise<EvalResultDetail> {
  const res = await authFetch(`${API_BASE}/evaluation/results/${encodeURIComponent(filename)}`)
  if (!res.ok) throw new Error(`Get result failed: ${res.statusText}`)
  return res.json()
}

export async function deleteResult(filename: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/evaluation/results/${encodeURIComponent(filename)}`, {
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
  const res = await authFetch(`${API_BASE}/evaluation/dataset/generate`, {
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

// ── Auth / User ──

export type UserRole = 'admin' | 'user' | 'guest'

export interface UserInfo {
  user_id: string
  username: string
  role: UserRole
  is_guest: boolean
  upload_used_today: number
  upload_limit: number  // -1 表示无限制（管理员）
  guest_chat_max_length: number
}

export interface LoginResponse {
  token: string
  username: string
  role: UserRole
  expires_at: string
}

export interface UploadQuota {
  used: number
  limit: number
  remaining: number
}

export interface AdminUser {
  user_id: string
  username: string
  role: UserRole
  active: number
  created_at: string
  updated_at: string
}

/** 提取后端错误信息（兼容 {detail: ...} / {error: ...} / 纯文本） */
async function extractError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    return body?.detail || body?.error || body?.message || fallback
  } catch {
    return fallback
  }
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    throw new Error(await extractError(res, `登录失败: ${res.statusText}`))
  }
  const data: LoginResponse = await res.json()
  setAuthToken(data.token)
  return data
}

export async function logout(): Promise<void> {
  try {
    await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' })
  } catch {
    /* ignore */
  }
  setAuthToken(null)
}

export async function getCurrentUser(): Promise<UserInfo> {
  const res = await authFetch(`${API_BASE}/auth/me`)
  if (!res.ok) {
    // 未登录或会话过期 — 返回访客身份，避免阻塞首屏
    return {
      user_id: '',
      username: 'guest',
      role: 'guest',
      is_guest: true,
      upload_used_today: 0,
      upload_limit: 0,
      guest_chat_max_length: 200,
    }
  }
  return res.json()
}

export async function register(username: string, password: string): Promise<UserInfo> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(await extractError(res, `注册失败: ${res.statusText}`))
  return res.json()
}

export async function changeMyPassword(oldPassword: string, newPassword: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/auth/password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  })
  if (!res.ok) throw new Error(await extractError(res, `修改密码失败: ${res.statusText}`))
}

export async function getUploadQuota(): Promise<UploadQuota> {
  const res = await authFetch(`${API_BASE}/auth/upload-quota`)
  if (!res.ok) throw new Error(`获取配额失败: ${res.statusText}`)
  return res.json()
}

// ── 管理员：用户管理 ──

export async function adminListUsers(): Promise<AdminUser[]> {
  const res = await authFetch(`${API_BASE}/auth/users`)
  if (!res.ok) throw new Error(await extractError(res, `获取用户列表失败: ${res.statusText}`))
  return res.json()
}

export async function adminCreateUser(username: string, password: string, role: UserRole): Promise<UserInfo> {
  const res = await authFetch(`${API_BASE}/auth/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  })
  if (!res.ok) throw new Error(await extractError(res, `创建用户失败: ${res.statusText}`))
  return res.json()
}

export async function adminUpdateUserRole(userId: string, role: UserRole): Promise<void> {
  const res = await authFetch(`${API_BASE}/auth/users/${userId}/role`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) throw new Error(await extractError(res, `修改角色失败: ${res.statusText}`))
}

export async function adminResetUserPassword(userId: string, newPassword: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/auth/users/${userId}/password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) throw new Error(await extractError(res, `重置密码失败: ${res.statusText}`))
}

export async function adminDeleteUser(userId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/auth/users/${userId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await extractError(res, `删除用户失败: ${res.statusText}`))
}

