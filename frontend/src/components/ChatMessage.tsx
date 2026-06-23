import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
import { User, Bot, Copy, Check, ChevronDown, ChevronRight, FileText, Search, Brain, GitGraph, MessageSquare, ShieldCheck, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useState, useRef, useMemo, useCallback } from 'react'
import type { RetreivedDoc, StreamStep } from '@/lib/api'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  query_type?: string
  citations?: string[]
  retrieved_docs?: RetreivedDoc[]
  steps?: StreamStep[]
  processing_time_ms?: number
}

const NODE_ICONS: Record<string, React.ReactNode> = {
  query_router: <Brain className="h-3 w-3" />,
  retrieval_agent: <Search className="h-3 w-3" />,
  graph_agent: <GitGraph className="h-3 w-3" />,
  graphrag_search: <GitGraph className="h-3 w-3" />,
  answer_generator: <MessageSquare className="h-3 w-3" />,
  answer_validator: <ShieldCheck className="h-3 w-3" />,
  chitchat: <MessageSquare className="h-3 w-3" />,
}

function StepIcon({ node }: { node: string }) {
  return <>{NODE_ICONS[node] || <Loader2 className="h-3 w-3" />}</>
}

function StepResult({ step }: { step: StreamStep }) {
  const [expanded, setExpanded] = useState(false)
  const result = step.result
  if (!result) return null

  if (step.node === 'query_router') {
    return (
      <span className="text-xs text-foreground/70 ml-1">
        → {String(result.query_type)} (置信度: {(Number(result.confidence) * 100).toFixed(0)}%)
      </span>
    )
  }
  if (step.node === 'retrieval_agent') {
    const count = result.count as number
    return (
      <span className="text-xs text-foreground/70 ml-1">
        → 检索到 {count} 条
        {count > 0 && (
          <button onClick={() => setExpanded(!expanded)} className="ml-1 text-primary hover:underline">
            {expanded ? '收起' : '详情'}
          </button>
        )}
        {expanded && (
          <div className="mt-1 space-y-1">
            {(result.documents as Array<Record<string, unknown>>)?.map((doc, i) => (
              <div key={i} className="bg-muted/30 rounded p-1.5 text-xs">
                <div className="text-muted-foreground">[{i + 1}] {String(doc.doc_id)}/{String(doc.chunk_id)} ({(Number(doc.score)).toFixed(3)})</div>
                <p className="whitespace-pre-wrap break-all">{doc.text as string}</p>
              </div>
            ))}
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

export function ChatMessage({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [activeCitation, setActiveCitation] = useState<number | null>(null)
  const chunkRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const isUser = message.role === 'user'

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleCitationClick = useCallback((seq: number) => {
    if (!message.retrieved_docs || seq > message.retrieved_docs.length) return
    setActiveCitation(seq)
    setShowContext(true)
    setTimeout(() => {
      const el = chunkRefs.current.get(seq)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 120)
  }, [message.retrieved_docs])

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
        if (!seq || !message.retrieved_docs || seq > message.retrieved_docs.length) {
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
  }), [message.retrieved_docs, handleCitationClick])

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isUser ? 'bg-primary' : 'bg-muted'}`}>
        {isUser ? <User className="h-4 w-4 text-primary-foreground" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={`flex-1 max-w-[80%] ${isUser ? 'text-right' : ''}`}>
        {message.steps && message.steps.length > 0 && (
          <div className="mb-2">
            <button
              onClick={() => setShowSteps(!showSteps)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-1"
            >
              {showSteps ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              处理过程 ({message.steps.length} 步)
            </button>
            {showSteps && (
              <div className="space-y-0.5 bg-muted/30 rounded p-2">
                {message.steps.map((step, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs">
                    <span className="shrink-0 mt-0.5"><StepIcon node={step.node} /></span>
                    <span className="text-muted-foreground">{step.label}</span>
                    <StepResult step={step} />
                    {step.status === 'error' && (
                      <span className="text-destructive ml-1">失败: {step.error}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {hasContent && (
          <div
            className={`inline-block rounded-lg px-4 py-2 ${
              isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}
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
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopy}>
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        )}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {message.citations.slice(0, 5).map((cit, i) => (
              <Badge
                key={i}
                variant="outline"
                className="text-xs cursor-pointer hover:bg-muted transition-colors"
                onClick={() => scrollToChunk(i + 1)}
                title="点击查看来源"
              >
                {cit}
              </Badge>
            ))}
          </div>
        )}
        {!isUser && message.retrieved_docs && message.retrieved_docs.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setShowContext(!showContext)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {showContext ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              检索上下文 ({message.retrieved_docs.length} 条)
            </button>
            {showContext && (
              <div className="mt-2 space-y-2">
                {message.retrieved_docs.map((doc, i) => (
                  <div
                    key={i}
                    id={`chunk-${i + 1}`}
                    ref={(el) => { if (el) chunkRefs.current.set(i + 1, el) }}
                    className={`bg-muted/50 rounded p-2 text-xs transition-all duration-300 ${
                      activeCitation === i + 1 ? 'ring-2 ring-primary bg-muted/70' : ''
                    }`}
                  >
                    <div className="flex items-center gap-1 text-muted-foreground mb-1">
                      <FileText className="h-3 w-3" />
                      {doc.filename || doc.doc_id}
                      <span className="ml-auto">score: {doc.score.toFixed(3)}</span>
                    </div>
                    <p className="whitespace-pre-wrap break-all leading-relaxed">{doc.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
