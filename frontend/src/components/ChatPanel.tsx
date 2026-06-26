import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Trash2, MessageSquare, Filter, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ChatMessage, type Message } from '@/components/ChatMessage'
import { askQuestionStream, type StreamStep, type RetrievedDoc } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'

const STORAGE_KEY = 'agentic_rag_chat_history'

function loadHistory(): Message[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function saveHistory(messages: Message[]) {
  const trimmed = messages.slice(-50)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
}

interface ChatPanelProps {
  folder: string | null
  docId?: string | null
  tags: string[]
}

export function ChatPanel({ folder, docId, tags }: ChatPanelProps) {
  const { user, isGuest } = useAuth()
  const [messages, setMessages] = useState<Message[]>(loadHistory)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 访客聊天输入长度上限（用于对外展示限制）
  const guestMax = user?.guest_chat_max_length ?? 200
  const maxLength = isGuest ? guestMax : undefined

  useEffect(() => {
    saveHistory(messages)
  }, [messages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const activeFilters = []
  if (docId) activeFilters.push(`文档: ${docId}`)
  else if (folder) activeFilters.push(`文件夹: ${folder}`)
  if (tags.length) activeFilters.push(`标签: ${tags.join(', ')}`)

  const handleSend = async () => {
    const query = input.trim()
    if (!query || isLoading) return
    if (isGuest && maxLength && query.length > maxLength) {
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: query },
        {
          role: 'assistant',
          content: `访客模式下单次提问不能超过 ${maxLength} 字符，请登录后继续使用。`,
        },
      ])
      setInput('')
      return
    }

    const userMsg: Message = { role: 'user', content: query }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    const steps: StreamStep[] = []
    let answer = ''
    let queryType = ''
    let citations: string[] = []
    let retrievedDocs: RetrievedDoc[] = []
    let processingTime = 0
    let searchDebugData: Record<string, unknown> | null = null

    setMessages((prev) => [...prev, { role: 'assistant', content: '', steps: [] }])

    try {
      await askQuestionStream(
        query,
        (step) => {
          steps.push(step)
          if (step.node === 'answer_generator' && step.result?.answer) {
            answer = step.result.answer as string
            citations = step.result.citations as string[] || []
          } else if (step.node === 'chitchat' && step.result?.answer) {
            answer = step.result.answer as string
          } else if (step.node === 'answer_validator' && step.result?.final_answer) {
            answer = step.result.final_answer as string
          }
          if (step.node === 'query_router' && step.result?.query_type) {
            queryType = step.result.query_type as string
          }
          if ((step.node === 'retrieval_agent' || step.node === 'lightrag_agent') && step.result?.documents) {
            retrievedDocs = (step.result.documents as Array<Record<string, unknown>>).map(d => ({
              doc_id: d.doc_id as string,
              chunk_id: d.chunk_id as string,
              text: d.text as string,
              score: d.score as number,
              rerank_score: d.rerank_score as number | null | undefined,
              dense_score: d.dense_score as number | null | undefined,
              bm25_score: d.bm25_score as number | null | undefined,
              filename: d.filename as string | undefined,
            }))
            if (step.result.search_debug_data) {
              searchDebugData = step.result.search_debug_data as Record<string, unknown>
            }
          }

          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: answer,
                query_type: queryType,
                citations,
                retrieved_docs: retrievedDocs,
                steps: [...steps],
                search_debug_data: searchDebugData,
              }
            }
            return updated
          })
        },
        (done) => {
          processingTime = done.processing_time_ms as number || 0
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: answer,
                query_type: queryType,
                citations,
                retrieved_docs: retrievedDocs,
                steps,
                processing_time_ms: processingTime,
                search_debug_data: searchDebugData,
              }
            }
            return updated
          })
          setIsLoading(false)
        },
        (err) => {
          setMessages((prev) => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              role: 'assistant',
              content: `请求失败: ${err}`,
            }
            return updated
          })
          setIsLoading(false)
        },
        folder || undefined,
        tags.length ? tags : undefined,
      )
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `请求失败: ${err instanceof Error ? err.message : String(err)}`,
        }
        return updated
      })
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const clearHistory = () => {
    setMessages([])
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <Card className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'var(--gradient-brand)' }}>
            <MessageSquare className="h-3.5 w-3.5 text-white" />
          </div>
          <span className="font-semibold text-base">智能问答</span>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={clearHistory} title="清空对话">
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Filter badges */}
      {activeFilters.length > 0 && (
        <div className="flex items-center gap-1.5 px-4 py-2 border-b bg-muted/20 shrink-0">
          <Filter className="h-3 w-3 text-muted-foreground" />
          {activeFilters.map((f, i) => (
            <Badge key={i} variant="secondary" className="text-xs">
              {f}
            </Badge>
          ))}
        </div>
      )}

      <CardContent className="flex-1 flex flex-col min-h-0 p-0">
        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4">
          <div className="space-y-4">
            {messages.length === 0 ? (
              <div className="text-center py-16">
                <div className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center" style={{ background: 'var(--gradient-brand)' }}>
                  <Sparkles className="h-8 w-8 text-white" />
                </div>
                <p className="text-sm font-medium text-foreground">输入问题开始对话</p>
                <p className="text-xs mt-1.5 text-muted-foreground">支持事实查询、多跳推理、对比分析、全局摘要</p>
                <div className="flex flex-wrap gap-2 justify-center mt-6">
                  {['什么是 RAG？', '对比向量检索与关键词检索', '系统支持哪些文档格式？'].map((s) => (
                    <button
                      key={s}
                      onClick={() => setInput(s)}
                      className="text-xs px-3 py-1.5 rounded-lg bg-muted/50 hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              (() => {
                let lastUserQuery = ''
                return messages.map((msg, i) => {
                  if (msg.role === 'user') lastUserQuery = msg.content
                  return <ChatMessage key={i} message={msg} userQuery={msg.role === 'assistant' ? lastUserQuery : undefined} />
                })
              })()
            )}
            {isLoading && (
              <div className="flex gap-3 animate-msg-in">
                <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-muted">
                  <BotIcon className="h-4 w-4" />
                </div>
                <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-typing-dot" style={{ animationDelay: '0s' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-typing-dot" style={{ animationDelay: '0.2s' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-typing-dot" style={{ animationDelay: '0.4s' }} />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Input */}
        <div className="border-t px-4 py-3 shrink-0">
          {isGuest && (
            <div className="flex items-center justify-between mb-1.5 text-[11px] text-muted-foreground">
              <span>访客模式：仅用于展示</span>
              <span className={input.length > (maxLength ?? 0) ? 'text-destructive' : ''}>
                {input.length}/{maxLength}
              </span>
            </div>
          )}
          <div className="flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isGuest ? '访客模式：输入问题进行体验（受字数限制）' : '输入你的问题...'}
              className="min-h-[44px] max-h-[120px] resize-none scrollbar-thin"
              rows={1}
              disabled={isLoading}
              maxLength={maxLength}
            />
            <Button
              onClick={handleSend}
              disabled={isLoading || !input.trim() || (!!maxLength && input.length > maxLength)}
              className="shrink-0 h-[44px] w-[44px] p-0"
              style={{ background: 'var(--gradient-brand)' }}
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function BotIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4" />
      <line x1="8" y1="16" x2="8" y2="16" />
      <line x1="16" y1="16" x2="16" y2="16" />
    </svg>
  )
}
