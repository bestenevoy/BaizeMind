// Mock data for Agent / Workflow orchestration visualization.
// 数据来源：src/agents/workflow.py（AgenticRAGWorkflow._build_graph）。
// 后端接口尚未实现，所有节点 / 边 / 场景均为前端 mock。

export type NodeCategory =
  | 'terminal'
  | 'router'
  | 'chat'
  | 'retrieval'
  | 'graph'
  | 'generator'
  | 'validator'

export interface WorkflowNode {
  id: string
  label: string
  codeName: string
  category: NodeCategory
  x: number
  y: number
  icon: string
  description: string
  inputs: string[]
  outputs: string[]
  source: string
  disabled?: boolean
  fallback?: boolean
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  label?: string
  routing?: 'straight' | 'top' | 'bottom'
  conditional?: boolean
  disabled?: boolean
  dashed?: boolean
}

export interface TraceStep {
  nodeId: string
  title: string
  note: string
  state: Record<string, unknown>
}

export interface Scenario {
  id: string
  label: string
  queryType: string
  query: string
  description: string
  path: string[]
  steps: TraceStep[]
}

// ── 画布尺寸（世界坐标，可平移/缩放的可编辑区域） ──
export const CANVAS_W = 3200
export const CANVAS_H = 2200
export const NODE_W = 196
export const NODE_H = 78

// ── 节点 ──
export const workflowNodes: WorkflowNode[] = [
  {
    id: 'START',
    label: '开始',
    codeName: 'START',
    category: 'terminal',
    x: 72,
    y: 340,
    icon: 'Play',
    description: 'LangGraph 入口，初始化 AgentState 并传入用户查询、folder、tags。',
    inputs: [],
    outputs: ['query', 'folder', 'tags', 'max_iterations'],
    source: 'workflow.py:270 invoke()',
  },
  {
    id: 'query_router',
    label: '查询路由',
    codeName: 'query_router',
    category: 'router',
    x: 278,
    y: 340,
    icon: 'Split',
    description:
      'LLM 分类查询类型 (chitchat / simple_fact / definition / multi_hop / comparison / holistic) 并判断 graph_eligible，决定后续分支。',
    inputs: ['query'],
    outputs: ['query_type', 'confidence', 'graph_eligible'],
    source: 'workflow.py:332 · query_router.py',
  },
  {
    id: 'chitchat',
    label: '闲聊直答',
    codeName: 'chitchat',
    category: 'chat',
    x: 538,
    y: 112,
    icon: 'MessageCircle',
    description: '闲聊分支：直接调用 LLM 生成回复，跳过检索与校验，直接结束。',
    inputs: ['query'],
    outputs: ['final_answer', 'draft_answer'],
    source: 'workflow.py:323',
  },
  {
    id: 'lightrag_agent',
    label: 'LightRAG 检索',
    codeName: 'lightrag_agent',
    category: 'graph',
    x: 538,
    y: 248,
    icon: 'Zap',
    description:
      'LightRAG 流程：实体 / 关系向量索引 → 图谱扩展 → 文档检索。索引为空时自动回退到 graph_agent + retrieval。',
    inputs: ['query', 'folder', 'tags'],
    outputs: ['documents', 'graph_context', 'graph_entities', 'retrieval_path'],
    source: 'workflow.py:490 · lightrag_retriever.py',
  },
  {
    id: 'retrieval_agent',
    label: '混合检索',
    codeName: 'retrieval_agent',
    category: 'retrieval',
    x: 538,
    y: 432,
    icon: 'Search',
    description:
      'Multi-Query 改写 → BM25 + 稠密向量 → RRF 融合 → Rerank，支持按 folder / tags 过滤；图谱实体词追加到 BM25。',
    inputs: ['query', 'graph_entities', 'sub_queries', 'folder', 'tags'],
    outputs: ['documents', 'retrieval_path', 'retrieval_debug', 'search_debug_data'],
    source: 'workflow.py:340 · retrieval_agent.py',
  },
  {
    id: 'graph_agent',
    label: '图谱扩展',
    codeName: 'graph_agent',
    category: 'graph',
    x: 538,
    y: 568,
    icon: 'Share2',
    description:
      '实体抽取 + Neo4j 图谱扩展，LLM 过滤相关实体并生成子问题供多路检索。当前仅作为 LightRAG 兜底路径。',
    inputs: ['query'],
    outputs: ['graph_context', 'graph_entities', 'sub_queries'],
    source: 'workflow.py:454 · graph_agent.py',
    fallback: true,
  },
  {
    id: 'graphrag_search',
    label: 'GraphRAG 检索',
    codeName: 'graphrag_search',
    category: 'graph',
    x: 800,
    y: 600,
    icon: 'Database',
    description:
      'Microsoft GraphRAG 全局 / drift 检索。已禁用：保留节点仅为图编译完整性，路由不可达。',
    inputs: ['query', 'query_type'],
    outputs: ['graphrag_context'],
    source: 'workflow.py:556 · graphrag_query.py',
    disabled: true,
  },
  {
    id: 'answer_generator',
    label: '答案生成',
    codeName: 'answer_generator',
    category: 'generator',
    x: 808,
    y: 340,
    icon: 'PenLine',
    description:
      'LLM 综合图谱上下文 + 检索文档生成答案，附引用 [N]；支持验证反馈重试，上下文按文档边界截断到 8000 字符。',
    inputs: ['query', 'documents', 'graph_context', 'graphrag_context', 'citations', 'validation_feedback'],
    outputs: ['draft_answer', 'citations'],
    source: 'workflow.py:580',
  },
  {
    id: 'answer_validator',
    label: '答案校验',
    codeName: 'answer_validator',
    category: 'validator',
    x: 1024,
    y: 340,
    icon: 'ShieldCheck',
    description:
      '校验答案：missing_citation / unsupported_claim / context_insufficient / conflict_detected。失败时按原因回退到 retrieval 或重生成。',
    inputs: ['query', 'documents', 'draft_answer', 'citations'],
    outputs: ['validation', 'validation_feedback', 'final_answer', 'iteration'],
    source: 'workflow.py:636 · answer_validator.py',
  },
  {
    id: 'END',
    label: '结束',
    codeName: 'END',
    category: 'terminal',
    x: 1196,
    y: 340,
    icon: 'CircleStop',
    description: '输出最终 final_answer、citations、retrieval_path 等状态。',
    inputs: ['final_answer', 'citations', 'retrieval_path'],
    outputs: [],
    source: 'workflow.py:266 END',
  },
]

// ── 边 ──
export const workflowEdges: WorkflowEdge[] = [
  { id: 'e1', source: 'START', target: 'query_router' },
  {
    id: 'e2',
    source: 'query_router',
    target: 'chitchat',
    label: 'chitchat',
    conditional: true,
  },
  {
    id: 'e3',
    source: 'query_router',
    target: 'lightrag_agent',
    label: 'multi_hop / comparison',
    conditional: true,
  },
  {
    id: 'e4',
    source: 'query_router',
    target: 'retrieval_agent',
    label: 'simple_fact / holistic',
    conditional: true,
  },
  {
    id: 'e5',
    source: 'chitchat',
    target: 'END',
    label: '直接回答',
    routing: 'top',
  },
  { id: 'e6', source: 'lightrag_agent', target: 'answer_generator' },
  { id: 'e7', source: 'retrieval_agent', target: 'answer_generator' },
  {
    id: 'e8',
    source: 'graph_agent',
    target: 'retrieval_agent',
    label: 'fallback · multi_hop',
    dashed: true,
    conditional: true,
  },
  {
    id: 'e9',
    source: 'graph_agent',
    target: 'answer_generator',
    label: 'fallback · else',
    dashed: true,
    conditional: true,
  },
  {
    id: 'e10',
    source: 'graphrag_search',
    target: 'answer_generator',
    label: '已禁用',
    dashed: true,
    disabled: true,
    conditional: true,
  },
  {
    id: 'e11',
    source: 'graphrag_search',
    target: 'retrieval_agent',
    label: '已禁用',
    dashed: true,
    disabled: true,
    conditional: true,
  },
  { id: 'e12', source: 'answer_generator', target: 'answer_validator' },
  {
    id: 'e13',
    source: 'answer_validator',
    target: 'END',
    label: 'valid ✓',
    conditional: true,
  },
  {
    id: 'e14',
    source: 'answer_validator',
    target: 'retrieval_agent',
    label: 'context_insufficient ↻',
    routing: 'bottom',
    conditional: true,
    dashed: true,
  },
  {
    id: 'e15',
    source: 'answer_validator',
    target: 'answer_generator',
    label: 'retry ↻',
    routing: 'top',
    conditional: true,
    dashed: true,
  },
]

// ── 场景（模拟执行轨迹） ──
export const scenarios: Scenario[] = [
  {
    id: 'chitchat',
    label: '闲聊',
    queryType: 'chitchat',
    query: '你好，你能帮我做什么？',
    description: '闲聊分支：路由判定为 chitchat 后直接调用 LLM 生成回复，跳过检索与校验。',
    path: ['START', 'query_router', 'chitchat', 'END'],
    steps: [
      {
        nodeId: 'START',
        title: '初始化状态',
        note: 'AgentState 注入 query，max_iterations 来自 settings。',
        state: { query: '你好，你能帮我做什么？', iteration: 0, max_iterations: 3 },
      },
      {
        nodeId: 'query_router',
        title: '查询分类',
        note: 'LLM 判定为 chitchat，graph_eligible=false。',
        state: { query_type: 'chitchat', confidence: 0.96, graph_eligible: false },
      },
      {
        nodeId: 'chitchat',
        title: '直接生成回复',
        note: '使用 CHITCHAT_SYSTEM prompt，单次 LLM 调用，无检索。',
        state: {
          draft_answer: '你好！我是一个基于 RAG 的问答助手，可以帮你查询已上传文档中的内容…',
          final_answer: '你好！我是一个基于 RAG 的问答助手，可以帮你查询已上传文档中的内容…',
        },
      },
      {
        nodeId: 'END',
        title: '返回结果',
        note: 'final_answer 直接输出，无 citations。',
        state: { final_answer: '你好！我是一个基于 RAG 的问答助手…', citations: [] },
      },
    ],
  },
  {
    id: 'simple_fact',
    label: '简单事实',
    queryType: 'simple_fact',
    query: 'BGE-M3 默认使用什么 Embedding API？',
    description:
      '简单事实查询（graph_eligible=false）：路由到 retrieval_agent 走混合检索，一次校验通过。',
    path: ['START', 'query_router', 'retrieval_agent', 'answer_generator', 'answer_validator', 'END'],
    steps: [
      {
        nodeId: 'START',
        title: '初始化状态',
        note: '用户提问，无 folder / tags 过滤。',
        state: { query: 'BGE-M3 默认使用什么 Embedding API？', folder: '', tags: [] },
      },
      {
        nodeId: 'query_router',
        title: '查询分类',
        note: '判定 simple_fact，graph_eligible=false → retrieval_agent。',
        state: { query_type: 'simple_fact', confidence: 0.91, graph_eligible: false },
      },
      {
        nodeId: 'retrieval_agent',
        title: 'Multi-Query 混合检索',
        note: '改写出 3 条 dense query + 1 条共享 bm25 query，RRF 融合后 rerank 取 top_k。',
        state: {
          documents: '8 chunks (rerank_top_k)',
          retrieval_path: '[Multi-query] 3 dense (Q0=原始) + 1 bm25',
          retrieval_debug: { rrf_total: 24, reranked_count: 8 },
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成带引用答案',
        note: '综合检索文档生成答案，附 [1][2] 引用。',
        state: {
          draft_answer: 'BGE-M3 默认使用 SiliconFlow API (BGE_M3_USE_LOCAL=false)…[1]',
          citations: ['[1] doc_01/chunk_4', '[2] doc_01/chunk_7'],
        },
      },
      {
        nodeId: 'answer_validator',
        title: '校验通过',
        note: 'is_valid=true，引用完整、有证据支撑。',
        state: { validation: { is_valid: true, failure_reasons: [] }, iteration: 1 },
      },
      {
        nodeId: 'END',
        title: '返回结果',
        note: '输出 final_answer 与 citations。',
        state: { final_answer: 'BGE-M3 默认使用 SiliconFlow API…', citations: ['[1] doc_01/chunk_4'] },
      },
    ],
  },
  {
    id: 'definition_graph',
    label: '图谱定义',
    queryType: 'definition',
    query: '什么是 LightRAG？它和 GraphRAG 有什么关系？',
    description:
      'definition 且 graph_eligible=true：路由到 lightrag_agent，通过实体 / 关系向量索引定位文档。',
    path: ['START', 'query_router', 'lightrag_agent', 'answer_generator', 'answer_validator', 'END'],
    steps: [
      {
        nodeId: 'START',
        title: '初始化状态',
        note: '提问涉及概念定义，可能需要图谱实体。',
        state: { query: '什么是 LightRAG？它和 GraphRAG 有什么关系？' },
      },
      {
        nodeId: 'query_router',
        title: '查询分类',
        note: '判定 definition 且 graph_eligible=true → lightrag_agent。',
        state: { query_type: 'definition', confidence: 0.88, graph_eligible: true },
      },
      {
        nodeId: 'lightrag_agent',
        title: 'LightRAG 实体检索',
        note: 'entity_index 命中 LightRAG/GraphRAG 实体，relation_index 扩展关联关系，召回相关 chunks。',
        state: {
          graph_entities: ['LightRAG', 'GraphRAG', 'entity_index', 'relation_index'],
          documents: '6 chunks',
          retrieval_path: '[LightRAG] entity→relation→expand→retrieve',
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成答案',
        note: '结合图谱上下文 + 检索文档生成对比说明。',
        state: {
          draft_answer: 'LightRAG 是基于实体/关系向量索引的轻量图谱检索方案…[1][2]',
          citations: ['[1] doc_03/chunk_2', '[2] doc_03/chunk_5'],
        },
      },
      {
        nodeId: 'answer_validator',
        title: '校验通过',
        note: 'is_valid=true。',
        state: { validation: { is_valid: true }, iteration: 1 },
      },
      {
        nodeId: 'END',
        title: '返回结果',
        note: '输出最终答案。',
        state: { final_answer: 'LightRAG 是基于实体/关系向量索引…' },
      },
    ],
  },
  {
    id: 'multi_hop_retry',
    label: '多跳·重试',
    queryType: 'multi_hop',
    query: '对比 BM25 和稠密向量检索在中文长文档上的优缺点',
    description:
      'multi_hop 路由到 lightrag_agent，首次校验 missing_citation → 回退 retrieval_agent 补充证据后重生成，第二次通过。',
    path: [
      'START',
      'query_router',
      'lightrag_agent',
      'answer_generator',
      'answer_validator',
      'retrieval_agent',
      'answer_generator',
      'answer_validator',
      'END',
    ],
    steps: [
      {
        nodeId: 'START',
        title: '初始化状态',
        note: '多跳对比类问题。',
        state: { query: '对比 BM25 和稠密向量检索在中文长文档上的优缺点' },
      },
      {
        nodeId: 'query_router',
        title: '查询分类',
        note: '判定 multi_hop → lightrag_agent。',
        state: { query_type: 'multi_hop', confidence: 0.84, graph_eligible: true },
      },
      {
        nodeId: 'lightrag_agent',
        title: 'LightRAG 检索',
        note: '实体索引命中 BM25 / 稠密向量，召回 5 chunks。',
        state: {
          graph_entities: ['BM25', '稠密向量', '检索'],
          documents: '5 chunks',
          retrieval_path: '[LightRAG] entity→relation→expand→retrieve',
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成答案（第 1 次）',
        note: '生成对比答案但未标注引用。',
        state: {
          draft_answer: 'BM25 擅长关键词匹配，稠密向量擅长语义召回…',
          citations: [],
          iteration: 0,
        },
      },
      {
        nodeId: 'answer_validator',
        title: '校验失败：missing_citation',
        note: '检测到事实性陈述缺少引用，feedback 提示补充 [N]，iteration=1。',
        state: {
          validation: { is_valid: false, failure_reasons: ['missing_citation'] },
          validation_feedback: 'Answer lacks source citations for factual claims…',
          iteration: 1,
        },
      },
      {
        nodeId: 'retrieval_agent',
        title: '补充检索（回退）',
        note: 'context_insufficient 未触发，此处由 answer_generator 重试，但补充更多证据 chunk。',
        state: {
          documents: '8 chunks (补充 3 条)',
          retrieval_path: '[Multi-query] 4 dense + 1 bm25 (retry)',
        },
      },
      {
        nodeId: 'answer_generator',
        title: '重生成答案（第 2 次）',
        note: '携带 validation_feedback 重新生成，补充引用。',
        state: {
          draft_answer: 'BM25 擅长关键词匹配…[1] 稠密向量擅长语义召回…[2][3]',
          citations: ['[1] doc_02/chunk_1', '[2] doc_02/chunk_3', '[3] doc_05/chunk_2'],
        },
      },
      {
        nodeId: 'answer_validator',
        title: '校验通过',
        note: 'is_valid=true，iteration=2 < max_iterations=3。',
        state: { validation: { is_valid: true }, iteration: 2 },
      },
      {
        nodeId: 'END',
        title: '返回结果',
        note: '输出带引用的最终对比答案。',
        state: { final_answer: 'BM25 擅长关键词匹配…[1]…', citations: ['[1]…', '[2]…', '[3]…'] },
      },
    ],
  },
]

// ── 节点模板（用于添加组件面板） ──
export interface NodeTemplate {
  type: string
  label: string
  codeName: string
  category: NodeCategory
  icon: string
  description: string
  inputs: string[]
  outputs: string[]
}

export const nodeTemplates: NodeTemplate[] = [
  {
    type: 'router',
    label: '查询路由',
    codeName: 'router',
    category: 'router',
    icon: 'Split',
    description: '根据输入分类，路由到不同分支节点。',
    inputs: ['input'],
    outputs: ['route'],
  },
  {
    type: 'retrieval',
    label: '检索',
    codeName: 'retrieval',
    category: 'retrieval',
    icon: 'Search',
    description: '从向量库 / BM25 检索相关文档。',
    inputs: ['query'],
    outputs: ['documents'],
  },
  {
    type: 'graph',
    label: '图谱',
    codeName: 'graph',
    category: 'graph',
    icon: 'Share2',
    description: '图谱实体扩展与子问题生成。',
    inputs: ['query'],
    outputs: ['graph_context'],
  },
  {
    type: 'generator',
    label: '生成',
    codeName: 'generator',
    category: 'generator',
    icon: 'PenLine',
    description: 'LLM 综合上下文生成答案。',
    inputs: ['context'],
    outputs: ['answer'],
  },
  {
    type: 'validator',
    label: '校验',
    codeName: 'validator',
    category: 'validator',
    icon: 'ShieldCheck',
    description: '校验答案，决定重试或结束。',
    inputs: ['answer'],
    outputs: ['validation'],
  },
  {
    type: 'chat',
    label: '闲聊',
    codeName: 'chat',
    category: 'chat',
    icon: 'MessageCircle',
    description: '直接 LLM 对话，无检索。',
    inputs: ['query'],
    outputs: ['answer'],
  },
  {
    type: 'terminal',
    label: '终端',
    codeName: 'terminal',
    category: 'terminal',
    icon: 'CircleStop',
    description: '流程开始 / 结束节点。',
    inputs: ['input'],
    outputs: [],
  },
]

// ── 分类色板 ──
export const categoryColors: Record<NodeCategory, { bar: string; ring: string; soft: string; text: string }> = {
  terminal: { bar: '#64748b', ring: '#94a3b8', soft: 'rgba(100,116,139,0.10)', text: '#475569' },
  router: { bar: '#8b5cf6', ring: '#a78bfa', soft: 'rgba(139,92,246,0.10)', text: '#6d28d9' },
  chat: { bar: '#06b6d4', ring: '#22d3ee', soft: 'rgba(6,182,212,0.10)', text: '#0e7490' },
  retrieval: { bar: '#3b82f6', ring: '#60a5fa', soft: 'rgba(59,130,246,0.10)', text: '#1d4ed8' },
  graph: { bar: '#10b981', ring: '#34d399', soft: 'rgba(16,185,129,0.10)', text: '#047857' },
  generator: { bar: '#f59e0b', ring: '#fbbf24', soft: 'rgba(245,158,11,0.10)', text: '#b45309' },
  validator: { bar: '#f43f5e', ring: '#fb7185', soft: 'rgba(244,63,94,0.10)', text: '#be123c' },
}
