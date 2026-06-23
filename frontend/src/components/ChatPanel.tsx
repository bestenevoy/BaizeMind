import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Trash2, MessageSquare, Filter } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ChatMessage, type Message } from '@/components/ChatMessage'
import { askQuestionStream, type StreamStep, type RetreivedDoc } from '@/lib/api'

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
  tags: string[]
}

export function ChatPanel({ folder, tags }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>(loadHistory)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    saveHistory(messages)
  }, [messages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const activeFilters = []
  if (folder) activeFilters.push(`文件夹: ${folder}`)
  if (tags.length) activeFilters.push(`标签: ${tags.join(', ')}`)

  const handleSend = async () => {
    const query = input.trim()
    if (!query || isLoading) return

    const userMsg: Message = { role: 'user', content: query }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    const steps: StreamStep[] = []
    let answer = ''
    let queryType = ''
    let citations: string[] = []
    let retrievedDocs: RetreivedDoc[] = []
    let processingTime = 0

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
          if (step.node === 'retrieval_agent' && step.result?.documents) {
            retrievedDocs = (step.result.documents as Array<Record<string, unknown>>).map(d => ({
              doc_id: d.doc_id as string,
              chunk_id: d.chunk_id as string,
              text: d.text as string,
              score: d.score as number,
              filename: d.filename as string | undefined,
            }))
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
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            智能问答
          </CardTitle>
          {messages.length > 0 && (
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={clearHistory}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
        {activeFilters.length > 0 && (
          <div className="flex items-center gap-1.5 mt-1">
            <Filter className="h-3 w-3 text-muted-foreground" />
            {activeFilters.map((f, i) => (
              <Badge key={i} variant="secondary" className="text-xs">
                {f}
              </Badge>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex-1 flex flex-col min-h-0">
        <ScrollArea className="flex-1 mb-4" ref={scrollRef}>
          <div className="space-y-4 pr-4">
            {messages.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <BotIcon className="mx-auto h-12 w-12 mb-4 opacity-50" />
                <p className="text-sm">输入问题开始对话</p>
                <p className="text-xs mt-1">支持事实查询、多跳推理、对比分析、全局摘要</p>
              </div>
            ) : (
              messages.map((msg, i) => <ChatMessage key={i} message={msg} />)
            )}
            {isLoading && (
              <div className="flex gap-3">
                <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-muted">
                  <BotIcon className="h-4 w-4" />
                </div>
                <div className="bg-muted rounded-lg px-4 py-3">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            className="min-h-[44px] max-h-[120px] resize-none"
            rows={1}
            disabled={isLoading}
          />
          <Button onClick={handleSend} disabled={isLoading || !input.trim()} className="shrink-0">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
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
