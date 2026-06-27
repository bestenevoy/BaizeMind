// Mock data for Agent / Workflow orchestration visualization.
// 数据来源：src/agents/workflow.py（AgenticRAGWorkflow._build_graph）。
// 后端接口尚未实现，所有节点 / 边 / 场景均为前端 mock。
//
// [UNIFIED] 统一召回 + LLM 决策 + 条件触发 SQL Tool Call 流程：
// - 所有非 chitchat 查询统一走向量召回（retrieval_agent / lightrag_agent）
// - answer_generator 合并了原 answer_validator 的职责（单次 LLM 生成 + 自检）
// - SQL 不再是独立路由，而是 answer_generator 之后的条件性 Tool Call
// - rerouted_to_sql=True 时直接 END（不再路由）

export type NodeCategory =
  | 'terminal'
  | 'router'
  | 'chat'
  | 'retrieval'
  | 'graph'
  | 'generator'
  | 'tool'

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
    description: 'LangGraph 入口，初始化 AgentState 并传入用户查询、folder、tags、doc_ids。',
    inputs: [],
    outputs: ['query', 'folder', 'tags', 'doc_ids', 'max_iterations'],
    source: 'workflow.py:invoke()',
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
      '[UNIFIED] LLM 仅做语义意图分类 (chitchat / simple_fact / definition / multi_hop / comparison / holistic) 并判断 graph_eligible。不决定 SQL 路由——所有非 chitchat 查询统一走向量召回。',
    inputs: ['query'],
    outputs: ['query_type', 'confidence', 'graph_eligible'],
    source: 'workflow.py:_node_query_router · query_router.py',
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
    source: 'workflow.py:_node_chitchat',
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
      '[统一召回] LightRAG 流程：实体 / 关系向量索引 → 图谱扩展 → 文档检索。索引为空时自动回退到 graph_agent + retrieval。文档块 + 表结构 + 表摘要同库召回。',
    inputs: ['query', 'folder', 'tags'],
    outputs: ['documents', 'graph_context', 'graph_entities', 'retrieval_path'],
    source: 'workflow.py:_node_lightrag_agent · lightrag_retriever.py',
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
      '[统一召回] Multi-Query 改写 → BM25 + 稠密向量 → RRF 融合 → Rerank，支持按 folder / tags / doc_ids 过滤。文档块 + 表结构 + 表摘要在同一向量库，不再区分 doc_query / sql_query。',
    inputs: ['query', 'graph_entities', 'sub_queries', 'folder', 'tags', 'doc_ids'],
    outputs: ['documents', 'retrieval_path', 'retrieval_debug', 'search_debug_data'],
    source: 'workflow.py:_node_retrieval_agent · retrieval_agent.py',
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
    source: 'workflow.py:_node_graph_agent · graph_agent.py',
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
    source: 'workflow.py:_node_graphrag_search · graphrag_query.py',
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
      '[MERGED] 单次 LLM 调用同时生成答案 + 自检（原 answer_validator 职责已合并）。综合统一召回上下文生成答案，附引用 [N]。输出本身即 LLM 对"召回是否充分"的决策：answer 正常 → 召回充分；answer 含"信息不足" → 进入条件性 SQL 触发判定。',
    inputs: ['query', 'documents', 'graph_context', 'graphrag_context', 'citations'],
    outputs: ['draft_answer', 'final_answer', 'citations', 'iteration', 'intermediate'],
    source: 'workflow.py:_node_answer_generator',
  },
  {
    id: 'sql_agent',
    label: 'SQL Tool Call',
    codeName: 'sql_agent',
    category: 'tool',
    x: 1024,
    y: 180,
    icon: 'Table',
    description:
      '[条件触发 Tool Call] 仅在 answer_generator 判定信息不足 + 召回含 excel_sheet chunk 时由 _route_after_generation 触发。NL2SQL：向量召回 Sheet → 多表选择 → 生成 SQL → 执行（含重试）。SQL 结果与上下文累加后回到 answer_generator 生成最终答案。不再 fallback 到 retrieval_agent。',
    inputs: ['query', 'folder', 'tags', 'doc_ids'],
    outputs: ['documents', 'retrieval_path', 'rerouted_to_sql', 'retrieval_debug'],
    source: 'workflow.py:_node_sql_agent · excel_rag/qa.py',
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
    source: 'workflow.py:END',
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
    label: 'multi_hop / comparison / graph_eligible',
    conditional: true,
  },
  {
    id: 'e4',
    source: 'query_router',
    target: 'retrieval_agent',
    label: 'simple_fact / definition / holistic',
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
  // [UNIFIED] answer_generator → _route_after_generation 条件路由：
  // - 召回充分 / 无数据表 → END
  // - 信息不足 + 有 excel_sheet chunk → sql_agent（条件触发 Tool Call）
  // - rerouted_to_sql=True → END（直接结束，不再路由）
  {
    id: 'e12',
    source: 'answer_generator',
    target: 'END',
    label: '召回充分 / 无数据表',
    conditional: true,
  },
  {
    id: 'e13',
    source: 'answer_generator',
    target: 'sql_agent',
    label: '信息不足 + excel_sheet',
    routing: 'top',
    conditional: true,
    dashed: true,
  },
  {
    id: 'e14',
    source: 'sql_agent',
    target: 'answer_generator',
    label: 'SQL 结果回流',
    routing: 'bottom',
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
        state: { query: '你好，你能帮我做什么？', iteration: 0, max_iterations: 5 },
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
      '[UNIFIED] 简单事实查询：统一召回 → answer_generator 生成 + 自检 → 召回充分 → END。',
    path: ['START', 'query_router', 'retrieval_agent', 'answer_generator', 'END'],
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
        note: '[UNIFIED] 判定 simple_fact，graph_eligible=false → retrieval_agent（不决定 SQL）。',
        state: { query_type: 'simple_fact', confidence: 0.91, graph_eligible: false },
      },
      {
        nodeId: 'retrieval_agent',
        title: '统一混合检索',
        note: '[统一召回] 改写出 3 条 dense query + 1 条共享 bm25 query，RRF 融合后 rerank 取 top_k。文档块 + 表结构 + 表摘要同库召回。',
        state: {
          documents: '8 chunks (rerank_top_k)',
          retrieval_path: '[Multi-query] 3 dense (Q0=原始) + 1 bm25',
          retrieval_debug: { rrf_total: 24, reranked_count: 8 },
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成 + 自检（召回充分）',
        note: '[MERGED] 单次 LLM 调用生成带引用答案。answer 正常 → _route_after_generation 判定召回充分 → END。',
        state: {
          draft_answer: 'BGE-M3 默认使用 SiliconFlow API (BGE_M3_USE_LOCAL=false)…[1]',
          final_answer: 'BGE-M3 默认使用 SiliconFlow API (BGE_M3_USE_LOCAL=false)…[1]',
          citations: ['[1] doc_01/chunk_4', '[2] doc_01/chunk_7'],
          iteration: 1,
        },
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
      '[UNIFIED] definition 且 graph_eligible=true：统一召回（LightRAG 路径）→ answer_generator 生成 + 自检 → 召回充分 → END。',
    path: ['START', 'query_router', 'lightrag_agent', 'answer_generator', 'END'],
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
        note: '[UNIFIED] 判定 definition 且 graph_eligible=true → lightrag_agent。',
        state: { query_type: 'definition', confidence: 0.88, graph_eligible: true },
      },
      {
        nodeId: 'lightrag_agent',
        title: 'LightRAG 统一召回',
        note: '[统一召回] entity_index 命中 LightRAG/GraphRAG 实体，relation_index 扩展关联关系，召回相关 chunks（含表摘要）。',
        state: {
          graph_entities: ['LightRAG', 'GraphRAG', 'entity_index', 'relation_index'],
          documents: '6 chunks',
          retrieval_path: '[LightRAG] entity→relation→expand→retrieve',
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成 + 自检（召回充分）',
        note: '[MERGED] 结合图谱上下文 + 检索文档生成对比说明。answer 正常 → END。',
        state: {
          draft_answer: 'LightRAG 是基于实体/关系向量索引的轻量图谱检索方案…[1][2]',
          final_answer: 'LightRAG 是基于实体/关系向量索引的轻量图谱检索方案…[1][2]',
          citations: ['[1] doc_03/chunk_2', '[2] doc_03/chunk_5'],
          iteration: 1,
        },
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
    id: 'excel_sql_toolcall',
    label: 'Excel·SQL Tool Call',
    queryType: 'simple_fact',
    query: '销售表中 2024 年 Q3 的总营收是多少？',
    description:
      '[UNIFIED] 统一召回（含 excel_sheet chunk）→ answer 信息不足 → 条件触发 SQL Tool Call → 基于 SQL 结果生成最终答案。对应设计文档第 2 点决策。',
    path: [
      'START',
      'query_router',
      'retrieval_agent',
      'answer_generator',
      'sql_agent',
      'answer_generator',
      'END',
    ],
    steps: [
      {
        nodeId: 'START',
        title: '初始化状态',
        note: '用户选了 Excel 文件提问，统一流程不再特殊路由。',
        state: { query: '销售表中 2024 年 Q3 的总营收是多少？', folder: '销售数据', tags: [] },
      },
      {
        nodeId: 'query_router',
        title: '查询分类',
        note: '[UNIFIED] 判定 simple_fact → retrieval_agent（不决定 SQL，统一走向量召回）。',
        state: { query_type: 'simple_fact', confidence: 0.89, graph_eligible: false },
      },
      {
        nodeId: 'retrieval_agent',
        title: '统一混合检索',
        note: '[统一召回] 召回文档块 + excel_sheet 摘要 chunk（metadata.source="excel_sheet"）。sheet 摘要含表结构/行数，但无具体数值。',
        state: {
          documents: '3 chunks (含 1 个 excel_sheet 摘要)',
          retrieval_path: '[Multi-query] 2 dense + 1 bm25',
          retrieval_debug: { rrf_total: 8, reranked_count: 3, has_excel_sheet: true },
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成 + 自检（信息不足）',
        note: '[MERGED] 基于召回上下文生成答案，但召回只有 sheet 摘要（表结构/行数），无具体数值 → answer 含"信息不足"。intermediate=True（前端延迟显示）。',
        state: {
          draft_answer: '提供的文档中没有足够的信息来回答这个问题。',
          final_answer: '提供的文档中没有足够的信息来回答这个问题。',
          citations: [],
          iteration: 1,
          intermediate: true,
          rerouted_to_sql: false,
        },
      },
      {
        nodeId: 'sql_agent',
        title: '条件触发 SQL Tool Call',
        note: '_route_after_generation 检测到：未重判 + 有 excel_sheet chunk + answer 信息不足 → 触发 NL2SQL。向量召回 Sheet → 多表选择 → 生成 SQL → 执行。返回 SQL 结果 documents，设置 rerouted_to_sql=True。',
        state: {
          documents: 'SQL 结果 1 条 (Sheet: sales_2024)',
          retrieval_path: 'sql_nl2sql',
          rerouted_to_sql: true,
          retrieval_debug: {
            sql_query: 'SELECT SUM(revenue) FROM sales_2024 WHERE quarter = "Q3" AND year = 2024',
            sql_sheet_name: 'sales_2024',
            sql_result_row_count: 1,
            sql_result_columns: ['SUM(revenue)'],
            sql_result_rows: [[1284500]],
          },
        },
      },
      {
        nodeId: 'answer_generator',
        title: '生成最终答案',
        note: '基于"sheet 摘要 + 真实 SQL 结果"生成最终答案。intermediate=False（前端渲染）。下一轮 _route_after_generation 检测 rerouted_to_sql=True → 直接 END。',
        state: {
          draft_answer: '2024 年 Q3 的总营收为 1,284,500 元 [1]',
          final_answer: '2024 年 Q3 的总营收为 1,284,500 元 [1]',
          citations: ['[1] excel:sales_2024/sales_2024'],
          iteration: 2,
          intermediate: false,
          rerouted_to_sql: true,
        },
      },
      {
        nodeId: 'END',
        title: '返回结果',
        note: 'rerouted_to_sql=True → 直接 END。输出最终答案与引用。',
        state: {
          final_answer: '2024 年 Q3 的总营收为 1,284,500 元 [1]',
          citations: ['[1] excel:sales_2024/sales_2024'],
          retrieval_path: 'sql_nl2sql',
        },
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
    type: 'tool',
    label: 'SQL 工具',
    codeName: 'tool',
    category: 'tool',
    icon: 'Table',
    description: '条件触发的 NL2SQL Tool Call，从数据表查询结构化数据。',
    inputs: ['query'],
    outputs: ['sql_result'],
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
  tool: { bar: '#6366f1', ring: '#818cf8', soft: 'rgba(99,102,241,0.10)', text: '#4338ca' },
}
