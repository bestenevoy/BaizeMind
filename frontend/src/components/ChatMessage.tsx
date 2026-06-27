import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
import { User, Bot, Copy, Check, ChevronDown, ChevronRight, FileText, Search, Brain, GitGraph, MessageSquare, Loader2, ExternalLink, Database } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useState, useRef, useMemo, useCallback } from 'react'
import type { RetrievedDoc, SheetColumn, StreamStep } from '@/lib/api'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  query_type?: string
  citations?: string[]
  retrieved_docs?: RetrievedDoc[]
  steps?: StreamStep[]
  processing_time_ms?: number
  search_debug_data?: Record<string, unknown> | null
}

const NODE_ICONS: Record<string, React.ReactNode> = {
  query_router: <Brain className="h-3 w-3" />,
  sql_agent: <Database className="h-3 w-3" />,
  retrieval_agent: <Search className="h-3 w-3" />,
  lightrag_agent: <Search className="h-3 w-3" />,
  graph_agent: <GitGraph className="h-3 w-3" />,
  graphrag_search: <GitGraph className="h-3 w-3" />,
  answer_generator: <MessageSquare className="h-3 w-3" />,
  chitchat: <MessageSquare className="h-3 w-3" />,
}

function StepIcon({ node }: { node: string }) {
  return <>{NODE_ICONS[node] || <Loader2 className="h-3 w-3" />}</>
}

function StepResult({ step, userQuery, searchDebugData }: { step: StreamStep; userQuery?: string; searchDebugData?: Record<string, unknown> | null }) {
  const [expanded, setExpanded] = useState(false)
  const result = step.result
  if (!result) return null
  const encodedQuery = userQuery ? encodeURIComponent(userQuery) : ''

  const handleAnalyze = () => {
    if (searchDebugData) {
      sessionStorage.setItem('chat_retrieval_debug', JSON.stringify(searchDebugData))
    }
    window.open(`/documents?tab=search&q=${encodedQuery}`, '_blank')
  }

  if (step.node === 'query_router') {
    return (
      <span className="text-xs text-foreground/70 ml-1">
        → {String(result.query_type)} (置信度: {(Number(result.confidence) * 100).toFixed(0)}%)
      </span>
    )
  }
  if (step.node === 'retrieval_agent' || step.node === 'lightrag_agent') {
    const count = result.count as number
    return (
      <span className="text-xs text-foreground/70 ml-1">
        → 检索到 {count} 条
        {count > 0 && (
          <button onClick={() => setExpanded(!expanded)} className="ml-1 text-primary hover:underline">
            {expanded ? '收起' : '详情'}
          </button>
        )}
        {count > 0 && userQuery && (
          <button onClick={handleAnalyze} className="ml-1.5 text-primary/70 hover:text-primary inline-flex items-center gap-0.5 text-xs" title="在检索测试页面分析（含完整检索数据）">
            <ExternalLink className="h-3 w-3" />
            分析
          </button>
        )}
        {expanded && (
          <div className="mt-1 space-y-1">
            {(result.documents as Array<Record<string, unknown>>)?.map((doc, i) => (
              <div key={i} className="bg-muted/30 rounded p-1.5 text-xs">
                <div className="text-muted-foreground">[{i + 1}] {String(doc.doc_id)}/{String(doc.chunk_id)}{doc.rerank_score != null ? ` rerank:${Number(doc.rerank_score).toFixed(3)}` : ''}{doc.dense_score != null ? ` dense:${Number(doc.dense_score).toFixed(3)}` : ''}{doc.bm25_score != null ? ` bm25:${Number(doc.bm25_score).toFixed(2)}` : ''}</div>
                <p className="whitespace-pre-wrap break-all">{doc.text as string}</p>
              </div>
            ))}
          </div>
        )}
      </span>
    )
  }
  if (step.node === 'sql_agent') {
    const retrievalPath = String(result.retrieval_path || '')
    const isSqlPath = retrievalPath === 'sql_nl2sql'
    const count = result.count as number
    const sqlQuery = result.sql_query as string | undefined
    const sheetName = result.sql_sheet_name as string | undefined
    const rowCount = Number(result.sql_result_row_count || 0)
    const recalledCount = Number(result.sql_recalled_count || 0)
    const sqlError = result.sql_error as string | undefined
    const fallbackReason = result.sql_fallback_reason as string | undefined
    // SQL 命中路径：result 顶层带 sql_result_columns / sql_result_rows（前 5 行）
    const sqlPreviewCols = (result.sql_result_columns as string[] | undefined) || []
    const sqlPreviewRows = (result.sql_result_rows as unknown[][] | undefined) || []
    return (
      <span className="text-xs text-foreground/70 ml-1">
        {isSqlPath ? (
          <>
            → SQL 检索：召回 {recalledCount} 表，命中
            {sheetName ? <span className="font-mono text-foreground"> {sheetName} </span> : ' '}
            · {rowCount} 行结果
            {sqlError && <span className="text-destructive"> · {sqlError}</span>}
          </>
        ) : (
          <>
            → SQL 未命中{fallbackReason ? `（${fallbackReason}）` : ''}，返回空结果
          </>
        )}
        {userQuery && (
          <button onClick={handleAnalyze} className="ml-1.5 text-primary/70 hover:text-primary inline-flex items-center gap-0.5 text-xs" title="在检索测试页面分析（含完整检索数据）">
            <ExternalLink className="h-3 w-3" />
            分析
          </button>
        )}
        {/* SQL 语句默认显示（截断 100 字符，点击查看完整 chunks） */}
        {isSqlPath && sqlQuery && (
          <div className="mt-1 bg-violet-50 dark:bg-violet-950/30 border-l-2 border-violet-300 dark:border-violet-700 rounded p-1.5 text-xs font-mono whitespace-pre-wrap break-all">
            <span className="text-violet-700 dark:text-violet-300 text-[10px] font-sans">SQL: </span>
            {sqlQuery.length > 100 ? sqlQuery.slice(0, 100) + '…' : sqlQuery}
          </div>
        )}
        {/* SQL 查询结果简要预览（前 5 行），让用户直观看到数据表内容 */}
        {isSqlPath && sqlPreviewCols.length > 0 && (
          <div className="mt-1 overflow-x-auto">
            <div className="text-[10px] text-muted-foreground mb-0.5">
              数据预览（{Math.min(sqlPreviewRows.length, 5)}/{rowCount} 行）
            </div>
            <table className="w-full text-[10px] border-collapse">
              <thead>
                <tr className="bg-muted/50">
                  {sqlPreviewCols.map((c, ci) => (
                    <th key={ci} className="border border-border/50 px-1.5 py-0.5 text-left font-mono whitespace-nowrap">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sqlPreviewRows.length === 0 ? (
                  <tr><td colSpan={sqlPreviewCols.length} className="border border-border/50 px-1.5 py-0.5 text-muted-foreground italic">(空结果)</td></tr>
                ) : sqlPreviewRows.slice(0, 5).map((row, ri) => (
                  <tr key={ri}>
                    {(Array.isArray(row) ? row : [row]).map((val, vi) => (
                      <td key={vi} className="border border-border/50 px-1.5 py-0.5 font-mono whitespace-nowrap">{String(val ?? '')}</td>
                    ))}
                  </tr>
                ))}
                {rowCount > sqlPreviewRows.length && (
                  <tr><td colSpan={sqlPreviewCols.length} className="border border-border/50 px-1.5 py-0.5 text-muted-foreground italic">… 共 {rowCount} 行，查看完整结果请展开「查询结果详情」</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        {/* chunks 默认折叠，点"详情"展开查看 */}
        {count > 0 && (
          <button onClick={() => setExpanded(!expanded)} className="ml-1 text-primary hover:underline">
            {expanded ? '收起' : `${isSqlPath ? '查询结果' : 'chunks'}详情`}
          </button>
        )}
        {expanded && (
          <div className="mt-1 space-y-1">
            {(result.documents as Array<Record<string, unknown>>)?.map((doc, i) => {
              const cols = (doc.sql_result_columns as string[] | undefined) || []
              const rows = (doc.sql_result_rows as unknown[][] | undefined) || []
              const rowCount = Number(doc.sql_result_row_count || 0)
              const isSqlDoc = String(doc.source_type || '') === 'sql' || cols.length > 0
              return (
                <div key={i} className="bg-muted/30 rounded p-1.5 text-xs">
                  <div className="text-muted-foreground flex items-center gap-1 flex-wrap">
                    <span>[{i + 1}]</span>
                    {Boolean(doc.filename) && <span className="truncate max-w-[140px]">{String(doc.filename)}</span>}
                    {Boolean(doc.sheet_name) && <Badge variant="secondary" className="text-[10px] font-mono">{String(doc.sheet_name)}</Badge>}
                    {Boolean(doc.source_type) && <span>· {String(doc.source_type)}</span>}
                    {isSqlDoc && rowCount > 0 && <span>· {rowCount} 行</span>}
                  </div>
                  {isSqlDoc && cols.length > 0 ? (
                    /* sql_agent 命中路径：直接渲染查询结果数据表，不显示 doc.text（text 截断后只看到表结构） */
                    <div className="mt-1 overflow-x-auto">
                      <table className="w-full text-[10px] border-collapse">
                        <thead>
                          <tr className="bg-muted/50">
                            {cols.map((c, ci) => (
                              <th key={ci} className="border border-border/50 px-1.5 py-0.5 text-left font-mono whitespace-nowrap">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.length === 0 ? (
                            <tr><td colSpan={cols.length} className="border border-border/50 px-1.5 py-0.5 text-muted-foreground italic">(空结果)</td></tr>
                          ) : rows.map((row, ri) => (
                            <tr key={ri}>
                              {(Array.isArray(row) ? row : [row]).map((val, vi) => (
                                <td key={vi} className="border border-border/50 px-1.5 py-0.5 font-mono whitespace-nowrap">{String(val ?? '')}</td>
                              ))}
                            </tr>
                          ))}
                          {rowCount > rows.length && (
                            <tr><td colSpan={cols.length} className="border border-border/50 px-1.5 py-0.5 text-muted-foreground italic">… 还有 {rowCount - rows.length} 行未显示</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    /* fallback 路径：显示文本 RAG 检索到的 chunk text */
                    <p className="whitespace-pre-wrap break-all mt-1">{doc.text as string}</p>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </span>
    )
  }
  if (step.node === 'graph_agent') {
    return (
      <span className="text-xs text-foreground/70 ml-1">
        → {result.has_context ? '找到图谱关联' : '未找到实体'}
      </span>
    )
  }
  return null
}

export function ChatMessage({ message, userQuery }: { message: Message; userQuery?: string }) {
  const [copied, setCopied] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [activeCitation, setActiveCitation] = useState<number | null>(null)
  const chunkRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const isUser = message.role === 'user'

  const handleCopy = async () => {
    const text = message.content || ''
    if (!text) return
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
      } else {
        // Fallback for non-secure context (HTTP) or unsupported clipboard API
        const textarea = document.createElement('textarea')
        textarea.value = text
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      console.error('Copy failed:', e)
    }
  }

  // Fallback: extract retrieved_docs from steps if message.retrieved_docs is missing
  const effectiveDocs = useMemo(() => {
    if (message.retrieved_docs && message.retrieved_docs.length > 0) return message.retrieved_docs
    const retrievalStep = message.steps?.find(
      s => (s.node === 'retrieval_agent' || s.node === 'lightrag_agent' || s.node === 'sql_agent') && s.result?.documents
    )
    if (!retrievalStep?.result?.documents) return message.retrieved_docs || []
    return (retrievalStep.result.documents as Array<Record<string, unknown>>).map(d => ({
      doc_id: d.doc_id as string || '',
      chunk_id: d.chunk_id as string || '',
      text: d.text as string || '',
      score: (typeof d.score === 'number' ? d.score : 0) as number,
      rerank_score: (typeof d.rerank_score === 'number' ? d.rerank_score : null) as number | null,
      dense_score: (typeof d.dense_score === 'number' ? d.dense_score : null) as number | null,
      bm25_score: (typeof d.bm25_score === 'number' ? d.bm25_score : null) as number | null,
      filename: d.filename as string | undefined,
      sheet_name: d.sheet_name as string | undefined,
      source_type: d.source_type as string | undefined,
      sql_result_columns: d.sql_result_columns as string[] | undefined,
      sql_result_rows: d.sql_result_rows as unknown[][] | undefined,
      sql_result_row_count: d.sql_result_row_count as number | undefined,
      sheet_row_count: d.sheet_row_count as number | undefined,
      sheet_columns: d.sheet_columns as SheetColumn[] | undefined,
    }))
  }, [message.retrieved_docs, message.steps])

  const handleCitationClick = useCallback((seq: number) => {
    if (!effectiveDocs || seq > effectiveDocs.length) return
    setActiveCitation(seq)
    setShowContext(true)
    setTimeout(() => {
      const el = chunkRefs.current.get(seq)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 120)
  }, [effectiveDocs])

  const scrollToChunk = useCallback((seq: number) => {
    handleCitationClick(seq)
  }, [handleCitationClick])

  const hasContent = message.content?.length > 0

  const processedContent = useMemo(() => {
    if (isUser || !hasContent) return message.content
    return message.content.replace(
      /\[(\d+)\]/g,
      (_: string, n: string) => `<a class="citation-ref" href="#chunk-${n}" data-seq="${n}">[${n}]</a>`
    )
  }, [message.content, isUser, hasContent])

  const markdownComponents = useMemo(() => ({
    p: ({ children, ...props }: React.HTMLProps<HTMLParagraphElement>) => <p className="mb-2 last:mb-0" {...props}>{children}</p>,
    a: ({ href, className, children, ...props }: React.HTMLProps<HTMLAnchorElement> & { 'data-seq'?: string }) => {
      if (className === 'citation-ref') {
        const seq = parseInt(props['data-seq'] || '0', 10)
        if (!seq || !effectiveDocs || seq > effectiveDocs.length) {
          return <span className="font-semibold text-primary/70">[{seq}]</span>
        }
        return (
          <a
            className="citation-ref inline-flex items-center"
            href={`#chunk-${seq}`}
            onClick={(e) => { e.preventDefault(); handleCitationClick(seq) }}
            title={`查看来源 #${seq}`}
            style={{
              cursor: 'pointer',
              fontWeight: 600,
              color: 'hsl(var(--primary))',
              textDecoration: 'underline',
              textUnderlineOffset: '2px'
            }}
          >
            {children}
          </a>
        )
      }
      return <a href={href} className="underline" target="_blank" rel="noopener noreferrer">{children}</a>
    },
    code: ({ className, children, ...props }: React.HTMLProps<HTMLElement>) => {
      const isInline = !className
      return isInline ? (
        <code className="bg-muted-foreground/10 px-1 py-0.5 rounded text-xs" {...props}>
          {children}
        </code>
      ) : (
        <pre className="bg-muted-foreground/10 p-2 rounded-md overflow-x-auto">
          <code className={className} {...props}>
            {children}
          </code>
        </pre>
      )
    },
    table: ({ children, ...props }: React.HTMLProps<HTMLTableElement>) => (
      <div className="overflow-x-auto my-2">
        <table className="min-w-full text-xs border-collapse" {...props}>{children}</table>
      </div>
    ),
    th: ({ children, ...props }: React.HTMLProps<HTMLTableHeaderCellElement>) => <th className="border border-border px-2 py-1 bg-muted font-semibold" {...props}>{children}</th>,
    td: ({ children, ...props }: React.HTMLProps<HTMLTableDataCellElement>) => <td className="border border-border px-2 py-1" {...props}>{children}</td>,
  }), [effectiveDocs, handleCitationClick])

  return (
    <div className={`flex gap-3 animate-msg-in ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isUser ? '' : 'bg-muted'}`} style={isUser ? { background: 'var(--gradient-brand)' } : {}}>
        {isUser ? <User className="h-4 w-4 text-white" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={`flex-1 max-w-[80%] ${isUser ? 'text-right' : ''}`}>
        {message.steps && message.steps.length > 0 && (() => {
          // 过滤掉 intermediate=true 的 answer_generator step（中间产物，会触发重判），
          // 避免处理过程显示两个"LLM 生成回答"步骤造成混淆
          const visibleSteps = message.steps.filter(
            s => !(s.node === 'answer_generator' && s.result?.intermediate === true)
          )
          if (visibleSteps.length === 0) return null
          return (
          <div className="mb-2">
            <button
              onClick={() => setShowSteps(!showSteps)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-1"
            >
              {showSteps ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              处理过程 ({visibleSteps.length} 步)
            </button>
            {showSteps && (
              <div className="space-y-0.5 bg-muted/30 rounded-lg p-2 text-left">
                {visibleSteps.map((step, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs">
                    <span className="shrink-0 mt-0.5"><StepIcon node={step.node} /></span>
                    <span className="text-muted-foreground">{step.label}</span>
                    <StepResult step={step} userQuery={userQuery} searchDebugData={message.search_debug_data} />
                    {step.status === 'error' && (
                      <span className="text-destructive ml-1">失败: {step.error}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          )
        })()}
        {hasContent && (
          <div
            className={`inline-block rounded-2xl px-4 py-2.5 text-left ${
              isUser ? 'text-white rounded-tr-sm' : 'bg-muted rounded-tl-sm'
            }`}
            style={isUser ? { background: 'var(--gradient-brand)' } : {}}
          >
            {isUser ? (
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
            ) : (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeRaw, rehypeKatex]}
                  components={markdownComponents}
                >
                  {processedContent}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}
        {isUser && hasContent && (
          <div className="flex justify-end mt-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleCopy}
              title="复制"
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        )}
        {!isUser && (
          <div className="flex items-center gap-2 mt-1">
            {message.query_type && (
              <Badge variant="secondary" className="text-xs">
                {message.query_type}
              </Badge>
            )}
            {message.processing_time_ms != null && (
              <span className="text-xs text-muted-foreground">
                {(message.processing_time_ms / 1000).toFixed(1)}s
              </span>
            )}
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopy} title="复制">
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        )}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {message.citations.slice(0, 5).map((cit, i) => {
              const doc = effectiveDocs?.[i]
              // 显示优先级：filename + sheet_name > doc_id
              // 避免显示 "af187512-9f9/excel:xxx" 这种截断 UUID 形式
              let displayRef: string
              if (doc) {
                const parts: string[] = [`[${i + 1}]`]
                if (doc.filename) parts.push(doc.filename)
                if (doc.sheet_name) parts.push(`· ${doc.sheet_name}`)
                // 没有 filename 时回退到 doc_id
                if (!doc.filename) parts.push(doc.doc_id)
                displayRef = parts.join(' ')
              } else {
                displayRef = cit
              }
              return (
                <Badge
                  key={i}
                  variant="outline"
                  className="text-xs cursor-pointer hover:bg-muted transition-colors"
                  onClick={() => scrollToChunk(i + 1)}
                  title="点击查看来源"
                >
                  {displayRef}
                  {doc && (
                    <span className="ml-1 text-muted-foreground">
                      {doc.rerank_score != null && <span className="text-primary/80">rerank:{doc.rerank_score.toFixed(3)}</span>}
                      {doc.dense_score != null && <span> dense:{doc.dense_score.toFixed(3)}</span>}
                      {doc.bm25_score != null && <span> bm25:{doc.bm25_score.toFixed(2)}</span>}
                    </span>
                  )}
                </Badge>
              )
            })}
          </div>
        )}
        {!isUser && effectiveDocs.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setShowContext(!showContext)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {showContext ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              检索上下文 ({effectiveDocs.length} 条)
            </button>
            {showContext && (
              <div className="mt-2 space-y-2">
                {effectiveDocs.map((doc, i) => {
                  const isSqlDoc = doc.source_type === 'sql'
                  const isSheetSummary = doc.source_type === 'sheet_summary'
                  return (
                    <div
                      key={i}
                      id={`chunk-${i + 1}`}
                      ref={(el) => { if (el) chunkRefs.current.set(i + 1, el) }}
                      className={`bg-muted/40 rounded-lg p-2.5 text-xs transition-all duration-300 border border-transparent ${
                        activeCitation === i + 1 ? 'ring-2 ring-primary bg-muted/60 border-primary/20' : ''
                      }`}
                    >
                      <div className="flex items-center gap-1 text-muted-foreground mb-1">
                        <FileText className="h-3 w-3" />
                        <span className="truncate">{doc.filename || doc.doc_id}</span>
                        {doc.sheet_name && (
                          <Badge variant="secondary" className="text-[10px] font-mono shrink-0">
                            {doc.sheet_name}
                          </Badge>
                        )}
                        {isSqlDoc && <Badge variant="outline" className="text-[10px] font-mono shrink-0">SQL 结果</Badge>}
                        {isSheetSummary && <Badge variant="outline" className="text-[10px] font-mono shrink-0">Sheet 摘要</Badge>}
                        <span className="ml-auto shrink-0 flex items-center gap-1.5 text-xs font-mono tabular-nums">
                          {doc.rerank_score != null && <span className="text-primary/80">rerank:{doc.rerank_score.toFixed(3)}</span>}
                          {doc.dense_score != null && <span>dense:{doc.dense_score.toFixed(3)}</span>}
                          {doc.bm25_score != null && <span>bm25:{doc.bm25_score.toFixed(2)}</span>}
                          {!isSqlDoc && !isSheetSummary && doc.score != null && <span>score:{doc.score.toFixed(3)}</span>}
                          {(isSqlDoc || isSheetSummary) && doc.score != null && <span>recall:{doc.score.toFixed(3)}</span>}
                        </span>
                      </div>
                      {isSqlDoc ? (
                        /* SQL 执行结果 doc：不显示截断的 text（前 300 字符只看到表结构），
                           引导用户查看 sql_agent step 的查询结果表格 */
                        <p className="text-muted-foreground italic">
                          SQL 执行结果，详见上方「SQL 检索 (NL2SQL)」步骤的查询结果表格
                        </p>
                      ) : isSheetSummary ? (
                        /* sheet_summary doc：结构化渲染 Sheet 卡片
                           Sheet 名 + 行数 + 摘要 + 列结构（与检索时索引数据表的元数据一致） */
                        <div className="space-y-1 leading-relaxed">
                          {doc.sheet_name && <div><span className="text-muted-foreground">Sheet:</span> {doc.sheet_name}</div>}
                          {doc.sheet_row_count != null && doc.sheet_row_count > 0 && (
                            <div><span className="text-muted-foreground">行数:</span> {doc.sheet_row_count}</div>
                          )}
                          {doc.text && (
                            <div>
                              <span className="text-muted-foreground">摘要:</span>
                              <p className="whitespace-pre-wrap break-all mt-0.5 scrollbar-thin max-h-24 overflow-y-auto">{doc.text}</p>
                            </div>
                          )}
                          {doc.sheet_columns && doc.sheet_columns.length > 0 && (
                            <div>
                              <span className="text-muted-foreground">列结构:</span>
                              <ul className="mt-0.5 space-y-0.5">
                                {doc.sheet_columns.map((c, ci) => (
                                  <li key={ci} className="font-mono text-[10px]">
                                    - {c.en} ({c.type}){c.cn ? ` → ${c.cn}` : ''}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="whitespace-pre-wrap break-all leading-relaxed scrollbar-thin max-h-32 overflow-y-auto">{doc.text}</p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
