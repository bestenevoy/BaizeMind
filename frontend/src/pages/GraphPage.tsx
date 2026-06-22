import { useState } from 'react'
import { FileText, Layers, Loader2, ExternalLink } from 'lucide-react'
import { GraphView } from '@/components/GraphView'
import { getEntityDetail, type EntityDetail } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'

export function GraphPage() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [detail, setDetail] = useState<EntityDetail | null>(null)
  const [loading, setLoading] = useState(false)

  const handleNodeClick = async (nodeId: string) => {
    setSelectedNode(nodeId)
    setLoading(true)
    try {
      const d = await getEntityDetail(nodeId)
      setDetail(d)
    } catch {
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Left: Graph */}
      <div className="flex-1 p-4 min-w-0">
        <Card className="h-full flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">知识图谱</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-2 min-h-0">
            <GraphView
              onNodeClick={handleNodeClick}
              selectedNode={selectedNode}
            />
          </CardContent>
        </Card>
      </div>

      {/* Right: Detail panel */}
      <div className="w-96 shrink-0 border-l p-4 flex flex-col">
        {!selectedNode ? (
          <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
            点击图中的节点查看详情
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : detail ? (
          <ScrollArea className="flex-1">
            <div className="space-y-4 pr-1">
              {/* Entity info */}
              <div>
                <h3 className="text-lg font-semibold">{detail.name}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="secondary" className="text-xs">
                    {detail.type || 'Unknown'}
                  </Badge>
                </div>
                {detail.description && (
                  <p className="text-sm text-muted-foreground mt-2">{detail.description}</p>
                )}
              </div>

              {/* Related Documents */}
              {detail.documents.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2 flex items-center gap-1">
                    <FileText className="h-3.5 w-3.5" />
                    相关文档 ({detail.documents.length})
                  </h4>
                  <div className="space-y-2">
                    {detail.documents.map((doc) => (
                      <div
                        key={doc.doc_id}
                        className="p-2 rounded-md border text-sm hover:bg-muted/50 transition-colors"
                      >
                        <div className="flex items-center gap-1.5">
                          <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          <span className="truncate font-medium">{doc.filename}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                          <span>{doc.folder}</span>
                          <span>·</span>
                          <span>{doc.chunk_count || 0} chunks</span>
                          <span>·</span>
                          <span>{doc.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Related Chunks */}
              {detail.related_chunks.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2 flex items-center gap-1">
                    <Layers className="h-3.5 w-3.5" />
                    相关 Chunks ({detail.related_chunks.length})
                  </h4>
                  <div className="space-y-2">
                    {detail.related_chunks.map((chunk) => (
                      <div
                        key={chunk.chunk_id}
                        className="p-2 rounded-md border text-xs hover:bg-muted/50 transition-colors"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <code className="text-[10px] text-muted-foreground">{chunk.chunk_id}</code>
                          {chunk.heading && (
                            <span className="text-[10px] text-muted-foreground bg-accent px-1 py-0.5 rounded">
                              {chunk.heading}
                            </span>
                          )}
                        </div>
                        <pre className="whitespace-pre-wrap break-all leading-relaxed max-h-[150px] overflow-y-auto text-muted-foreground">
                          {chunk.text}
                        </pre>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {detail.documents.length === 0 && detail.related_chunks.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无关联数据</p>
              )}
            </div>
          </ScrollArea>
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
            加载失败
          </div>
        )}
      </div>
    </div>
  )
}
