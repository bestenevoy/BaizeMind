import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { CheckCircle2, AlertTriangle, Beaker, FlaskConical, Server, Layers, BookOpen, Search, Brain } from 'lucide-react'

interface TestModule {
  file: string
  icon: typeof Beaker
  description: string
  needs_services: boolean
  tests: { name: string; description: string }[]
}

const testModules: TestModule[] = [
  {
    file: 'tests/test_parser.py',
    icon: BookOpen,
    description: '文档解析模块测试',
    needs_services: false,
    tests: [
      { name: 'test_table_parser_html', description: 'HTML 表格解析（caption/headers/rows）' },
      { name: 'test_table_parser_markdown', description: 'Markdown 表格提取' },
      { name: 'test_cross_page_merge', description: '跨页表格合并' },
    ],
  },
  {
    file: 'tests/test_chunker.py',
    icon: Layers,
    description: '文本分块模块测试',
    needs_services: false,
    tests: [
      { name: 'test_hierarchical_chunker_basic', description: 'Markdown 层级分块' },
      { name: 'test_table_chunker', description: '表格感知分块（大表拆分）' },
      { name: 'test_context_merger', description: '相邻块上下文合并' },
    ],
  },
  {
    file: 'tests/test_graph.py',
    icon: Server,
    description: '知识图谱模块测试',
    needs_services: false,
    tests: [
      { name: 'test_entity_extractor_parse', description: '实体抽取结果解析' },
      { name: 'test_neo4j_manager_init', description: 'Neo4j 管理器初始化' },
    ],
  },
  {
    file: 'tests/test_retrieval.py',
    icon: Search,
    description: '检索模块测试 (需 Milvus)',
    needs_services: true,
    tests: [
      { name: 'test_hybrid_retriever_init', description: '混合检索器初始化' },
      { name: 'test_bm25_retriever', description: 'BM25 索引构建与搜索' },
      { name: 'test_rrf_fusion', description: 'RRF 融合排序' },
      { name: 'test_reranker_score', description: '重排序评分 (TF-IDF)' },
    ],
  },
  {
    file: 'tests/test_agents.py',
    icon: Brain,
    description: 'Agent 智能体模块测试 (需 Milvus/模型)',
    needs_services: true,
    tests: [
      { name: 'test_query_router_classify', description: '查询路由分类解析' },
      { name: 'test_answer_validator_parse', description: '答案校验解析' },
      { name: 'test_workflow_init', description: '工作流图形编译初始化' },
    ],
  },
]

export function TestsPage() {
  const safeModules = testModules.filter((m) => !m.needs_services)
  const serviceModules = testModules.filter((m) => m.needs_services)
  const totalTests = testModules.reduce((s, m) => s + m.tests.length, 0)

  return (
    <div className="container mx-auto py-6 px-4 max-w-4xl">
      <div className="space-y-6">

        {/* Summary Header */}
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <FlaskConical className="h-8 w-8 text-primary" />
              <div>
                <h1 className="text-xl font-bold">测试概览</h1>
                <p className="text-sm text-muted-foreground">
                  共 {testModules.length} 个测试模块，{totalTests} 个测试用例
                </p>
              </div>
              <div className="ml-auto flex gap-2">
                <Badge variant="outline" className="gap-1">
                  <CheckCircle2 className="h-3 w-3 text-green-500" />
                  {safeModules.length} 模块可离线运行
                </Badge>
                <Badge variant="outline" className="gap-1">
                  <AlertTriangle className="h-3 w-3 text-yellow-500" />
                  {serviceModules.length} 模块需外部服务
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Safe Unit Tests (no external services) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-500" />
              离线单元测试
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              这些测试不依赖外部服务（Milvus / Neo4j / API），可随时运行
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              <div className="relative px-3 py-2 rounded-md bg-muted/50 text-xs text-muted-foreground font-mono overflow-hidden">
                <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-green-500/60" />
                <span className="pl-1">uv run -m pytest {safeModules.map(m => m.file).join(' ')} -v</span>
              </div>
            </div>
            <Separator className="my-3" />
            {safeModules.map((mod) => (
              <div key={mod.file} className="mb-4 last:mb-0">
                <div className="flex items-center gap-2 mb-2">
                  <mod.icon className="h-4 w-4 text-primary" />
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground font-mono">{mod.file}</h4>
                  <Badge variant="secondary" className="text-xs">{mod.description}</Badge>
                </div>
                <div className="grid grid-cols-1 gap-1.5 pl-6">
                  {mod.tests.map((t) => (
                    <div key={t.name} className="flex items-start gap-2 text-sm">
                      <span className="text-muted-foreground mt-0.5 shrink-0">•</span>
                      <div>
                        <code className="text-xs bg-muted px-1 rounded">{t.name}</code>
                        <span className="text-muted-foreground ml-2 text-xs">{t.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Integration Tests (need services) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-yellow-500" />
              集成测试（需外部服务）
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              需要 Milvus / Neo4j / DeepSeek API 运行。服务不可用时可能挂起。
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              <div className="relative px-3 py-2 rounded-md bg-muted/50 text-xs text-muted-foreground font-mono overflow-hidden">
                <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-yellow-500/60" />
                <span className="pl-1">uv run -m pytest {serviceModules.map(m => m.file).join(' ')} -v</span>
              </div>
            </div>
            <Separator className="my-3" />
            {serviceModules.map((mod) => (
              <div key={mod.file} className="mb-4 last:mb-0">
                <div className="flex items-center gap-2 mb-2">
                  <mod.icon className="h-4 w-4 text-yellow-500" />
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground font-mono">{mod.file}</h4>
                  <Badge variant="secondary" className="text-xs">{mod.description}</Badge>
                </div>
                <div className="grid grid-cols-1 gap-1.5 pl-6">
                  {mod.tests.map((t) => (
                    <div key={t.name} className="flex items-start gap-2 text-sm">
                      <span className="text-muted-foreground mt-0.5 shrink-0">•</span>
                      <div>
                        <code className="text-xs bg-muted px-1 rounded">{t.name}</code>
                        <span className="text-muted-foreground ml-2 text-xs">{t.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

      </div>
    </div>
  )
}
