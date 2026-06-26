import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Workflow,
  Play,
  Pause,
  RotateCcw,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  CornerDownLeft,
  Info,
  Maximize2,
  Minimize2,
  Plus,
  Trash2,
  Split,
  Search,
  Share2,
  PenLine,
  ShieldCheck,
  MessageCircle,
  CircleStop,
  type LucideIcon,
} from 'lucide-react'
import { WorkflowGraph } from '@/components/WorkflowGraph'
import {
  workflowNodes as defaultNodes,
  workflowEdges as defaultEdges,
  scenarios,
  categoryColors,
  nodeTemplates,
  type Scenario,
  type WorkflowNode,
  type WorkflowEdge,
  type NodeTemplate,
} from '@/data/workflowMock'

// 由路径（节点 id 序列）推导经过的边 id
function pathToEdges(path: string[], edges: WorkflowEdge[]): Set<string> {
  const result = new Set<string>()
  for (let i = 0; i < path.length - 1; i++) {
    const edge = edges.find((e) => e.source === path[i] && e.target === path[i + 1])
    if (edge) result.add(edge.id)
  }
  return result
}

function StateValue({ k, v }: { k: string; v: unknown }) {
  const renderVal = () => {
    if (v === null || v === undefined) return <span className="text-muted-foreground/60">∅</span>
    if (typeof v === 'boolean') return <code className="text-xs">{String(v)}</code>
    if (typeof v === 'number') return <code className="text-xs tabular-nums">{v}</code>
    if (typeof v === 'string') {
      const display = v.length > 120 ? v.slice(0, 120) + '…' : v
      return <span className="text-xs text-foreground/90">{display}</span>
    }
    if (Array.isArray(v)) {
      if (v.length === 0) return <code className="text-xs text-muted-foreground">[]</code>
      return (
        <div className="flex flex-wrap gap-1">
          {v.map((item, i) => (
            <code key={i} className="text-[10px] px-1 py-0.5 rounded bg-muted">
              {String(item)}
            </code>
          ))}
        </div>
      )
    }
    return <code className="text-xs">{JSON.stringify(v)}</code>
  }
  return (
    <div className="flex items-start gap-2 py-1">
      <code className="text-[10.5px] text-muted-foreground shrink-0 w-32 truncate" title={k}>
        {k}
      </code>
      <span className="text-muted-foreground/40 shrink-0">:</span>
      <div className="min-w-0 flex-1">{renderVal()}</div>
    </div>
  )
}

const templateIconMap: Record<string, LucideIcon> = {
  Split,
  Search,
  Share2,
  PenLine,
  ShieldCheck,
  MessageCircle,
  CircleStop,
}

export function WorkflowPage() {
  const [nodes, setNodes] = useState<WorkflowNode[]>(() => defaultNodes.map((n) => ({ ...n })))
  const [edges, setEdges] = useState<WorkflowEdge[]>(() => defaultEdges.map((e) => ({ ...e })))
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [stepIdx, setStepIdx] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const addCounter = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const totalSteps = scenario?.steps.length ?? 0

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  // 自动播放
  useEffect(() => {
    if (!playing || !scenario) return
    if (stepIdx === null) {
      setStepIdx(0)
      return
    }
    if (stepIdx >= totalSteps - 1) {
      setPlaying(false)
      return
    }
    timerRef.current = setInterval(() => {
      setStepIdx((prev) => {
        if (prev === null) return 0
        if (prev >= totalSteps - 1) {
          setPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, 1100)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [playing, scenario, stepIdx, totalSteps])

  // 键盘：Delete 删除选中节点，Escape 退出全屏
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const tag = el?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNode) {
        e.preventDefault()
        deleteNode(selectedNode)
      }
      if (e.key === 'Escape' && fullscreen) setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode, fullscreen])

  const selectScenario = (s: Scenario) => {
    setScenario(s)
    setStepIdx(null)
    setPlaying(false)
    setSelectedNode(null)
  }

  const reset = () => {
    setStepIdx(null)
    setPlaying(false)
  }

  const stepForward = () => {
    if (!scenario) return
    setStepIdx((prev) => (prev === null ? 0 : Math.min(prev + 1, totalSteps - 1)))
  }
  const stepBack = () => {
    if (!scenario) return
    setStepIdx((prev) => (prev === null ? null : Math.max(prev - 1, 0)))
  }

  const addNode = (tpl: NodeTemplate) => {
    addCounter.current += 1
    const id = `${tpl.type}_${Date.now().toString(36)}_${addCounter.current}`
    const baseX = 700
    const baseY = 340
    const offset = (addCounter.current % 6) * 26
    const newNode: WorkflowNode = {
      id,
      label: tpl.label,
      codeName: `${tpl.codeName}_${addCounter.current}`,
      category: tpl.category,
      x: baseX + offset,
      y: baseY + offset,
      icon: tpl.icon,
      description: tpl.description,
      inputs: [...tpl.inputs],
      outputs: [...tpl.outputs],
      source: '自定义节点',
    }
    setNodes((prev) => [...prev, newNode])
    setSelectedNode(id)
  }

  const deleteNode = (id: string) => {
    setNodes((prev) => prev.filter((n) => n.id !== id))
    setEdges((prev) => prev.filter((e) => e.source !== id && e.target !== id))
    if (selectedNode === id) setSelectedNode(null)
  }

  const moveNode = (id: string, x: number, y: number) => {
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, x, y } : n)))
  }

  const resetGraph = () => {
    setNodes(defaultNodes.map((n) => ({ ...n })))
    setEdges(defaultEdges.map((e) => ({ ...e })))
    setSelectedNode(null)
  }

  const { activeNodes, activeEdges, currentNode } = useMemo(() => {
    if (!scenario) return { activeNodes: new Set<string>(), activeEdges: new Set<string>(), currentNode: null }
    const nSet = new Set(scenario.path)
    const eSet = pathToEdges(scenario.path, edges)
    const cur = stepIdx !== null ? scenario.steps[stepIdx]?.nodeId ?? null : null
    return { activeNodes: nSet, activeEdges: eSet, currentNode: cur }
  }, [scenario, stepIdx, edges])

  const selectedNodeData = selectedNode ? nodeMap.get(selectedNode) ?? null : null
  const currentStep = scenario && stepIdx !== null ? scenario.steps[stepIdx] : null
  const currentNodeData = currentStep ? nodeMap.get(currentStep.nodeId) ?? null : null
  const detailNode = currentNodeData ?? selectedNodeData
  const detailStep = currentStep

  const editor = (
    <>
      {/* ── 主区域 ── */}
      <div className="flex-1 min-w-0 flex flex-col p-4 gap-3">
        {/* 标题 + 控件 */}
        <Card className="flex-none">
          <CardContent className="py-3">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'var(--gradient-brand)' }}>
                  <Workflow className="h-4 w-4 text-white" />
                </div>
                <div>
                  <h1 className="text-base font-bold leading-tight">Workflow 编排</h1>
                  <p className="text-[11px] text-muted-foreground leading-tight">
                    LangGraph · 可视化编辑（前端 Mock）
                  </p>
                </div>
              </div>
              <Separator orientation="vertical" className="h-9" />
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  场景
                </span>
                {scenarios.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => selectScenario(s)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                      scenario?.id === s.id
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-card text-muted-foreground border-border hover:text-foreground hover:bg-accent'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1.5">
                <Badge variant="outline" className="text-[10px] gap-1">
                  <Info className="h-3 w-3" />
                  Mock
                </Badge>
                <Separator orientation="vertical" className="h-7" />
                <Button variant="outline" size="sm" onClick={resetGraph} title="重置为默认图">
                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                  重置图
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setFullscreen((f) => !f)}
                  title={fullscreen ? '退出全屏 (Esc)' : '全屏编辑'}
                >
                  {fullscreen ? <Minimize2 className="h-3.5 w-3.5 mr-1" /> : <Maximize2 className="h-3.5 w-3.5 mr-1" />}
                  {fullscreen ? '退出全屏' : '全屏'}
                </Button>
              </div>
            </div>

            {/* 添加组件面板 + 播放控件 */}
            <div className="mt-3 flex items-center gap-2 flex-wrap">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <Plus className="h-3 w-3" />
                添加
              </span>
              {nodeTemplates.map((tpl) => {
                const Icon = templateIconMap[tpl.icon] ?? CircleStop
                const color = categoryColors[tpl.category]
                return (
                  <button
                    key={tpl.type}
                    onClick={() => addNode(tpl)}
                    title={tpl.description}
                    className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                  >
                    <span
                      className="w-4 h-4 rounded flex items-center justify-center"
                      style={{ background: color.soft, color: color.text }}
                    >
                      <Icon style={{ width: 11, height: 11 }} />
                    </span>
                    {tpl.label}
                  </button>
                )
              })}
              <div className="ml-auto flex items-center gap-1.5">
                <Button variant="outline" size="sm" onClick={stepBack} disabled={!scenario || stepIdx === null || stepIdx === 0} title="上一步">
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant={playing ? 'secondary' : 'default'}
                  size="sm"
                  onClick={() => {
                    if (!scenario) return
                    if (stepIdx === null) setStepIdx(0)
                    setPlaying((p) => !p)
                  }}
                  disabled={!scenario}
                >
                  {playing ? <Pause className="h-3.5 w-3.5 mr-1" /> : <Play className="h-3.5 w-3.5 mr-1" />}
                  {playing ? '暂停' : stepIdx === null ? '播放' : stepIdx >= totalSteps - 1 ? '完成' : '继续'}
                </Button>
                <Button variant="outline" size="sm" onClick={stepForward} disabled={!scenario || stepIdx === null || stepIdx >= totalSteps - 1} title="下一步">
                  <ChevronRight className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={reset} disabled={!scenario || stepIdx === null} title="重置播放">
                  <RotateCcw className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {scenario && (
              <div className="mt-3 flex items-center gap-2 text-xs">
                <Badge variant="secondary" className="text-[10px] font-mono">{scenario.queryType}</Badge>
                <span className="text-muted-foreground">query:</span>
                <code className="text-foreground/90 bg-muted px-1.5 py-0.5 rounded">{scenario.query}</code>
                {stepIdx !== null && (
                  <span className="ml-auto text-muted-foreground tabular-nums">
                    step {stepIdx + 1} / {totalSteps}
                  </span>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 画布 */}
        <Card className="flex-1 min-h-0 flex flex-col">
          <CardHeader className="pb-2 pt-3 flex-row items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <Workflow className="h-4 w-4 text-primary" />
              工作流图
              <span className="text-[10px] text-muted-foreground font-normal">
                拖拽空白平移 · 滚轮缩放 · 拖动节点调整位置 · Delete 删除
              </span>
            </CardTitle>
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              {(['terminal', 'router', 'retrieval', 'graph', 'generator', 'validator', 'chat'] as const).map((cat) => (
                <span key={cat} className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ background: categoryColors[cat].bar }} />
                  {cat}
                </span>
              ))}
            </div>
          </CardHeader>
          <CardContent className="flex-1 min-h-0 p-0">
            <WorkflowGraph
              nodes={nodes}
              edges={edges}
              activePathNodes={activeNodes}
              activePathEdges={activeEdges}
              currentNode={currentNode}
              selectedNode={selectedNode}
              onNodeClick={(id) => setSelectedNode(id)}
              onNodeMove={moveNode}
              onDeleteNode={deleteNode}
              onBackgroundClick={() => setSelectedNode(null)}
            />
          </CardContent>
        </Card>

        {/* 步骤时间线 */}
        {scenario && stepIdx !== null && (
          <Card className="flex-none">
            <CardContent className="py-2.5">
              <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin pb-1">
                {scenario.steps.map((st, i) => {
                  const n = nodeMap.get(st.nodeId)
                  const done = i < stepIdx
                  const active = i === stepIdx
                  const color = n ? categoryColors[n.category] : categoryColors.terminal
                  return (
                    <div key={i} className="flex items-center shrink-0">
                      <button
                        onClick={() => setStepIdx(i)}
                        className="flex flex-col items-center gap-0.5 px-2 py-1 rounded-md transition-colors hover:bg-accent"
                        style={active ? { background: color.soft } : undefined}
                      >
                        <span
                          className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border-2 transition-all"
                          style={{
                            borderColor: done || active ? color.bar : 'hsl(var(--border))',
                            background: done ? color.bar : active ? color.soft : 'transparent',
                            color: done ? '#fff' : active ? color.text : 'hsl(var(--muted-foreground))',
                          }}
                        >
                          {i + 1}
                        </span>
                        <span className="text-[10px] font-medium whitespace-nowrap" style={{ color: active ? color.text : 'hsl(var(--muted-foreground))' }}>
                          {n?.label ?? st.nodeId}
                        </span>
                      </button>
                      {i < scenario.steps.length - 1 && (
                        <ChevronRight className="h-3 w-3 text-muted-foreground/50 shrink-0" />
                      )}
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ── 右侧详情面板 ── */}
      <div className="w-80 shrink-0 border-l flex flex-col min-h-0">
        <ScrollArea className="flex-1">
          <div className="p-4 space-y-4">
            {!detailNode ? (
              <div className="flex flex-col items-center justify-center h-64 text-center gap-2">
                <Workflow className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  点击节点查看详情
                  <br />
                  拖动节点调整位置
                  <br />
                  选中后按 Delete 删除
                </p>
              </div>
            ) : (
              <>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-1 h-5 rounded-sm" style={{ background: categoryColors[detailNode.category].bar }} />
                    <h3 className="text-base font-bold">{detailNode.label}</h3>
                    {detailNode.fallback && !detailNode.disabled && (
                      <Badge variant="outline" className="text-[9px] text-amber-600 border-amber-300">兜底</Badge>
                    )}
                    {detailNode.disabled && (
                      <Badge variant="outline" className="text-[9px] text-slate-500">已禁用</Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 ml-auto"
                      onClick={() => deleteNode(detailNode.id)}
                      title="删除节点"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </div>
                  <code className="text-[11px] text-muted-foreground font-mono">{detailNode.codeName}</code>
                  <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{detailNode.description}</p>
                </div>

                <Separator />

                {detailStep && (
                  <div className="rounded-lg border p-2.5" style={{ background: categoryColors[detailNode.category].soft }}>
                    <div className="flex items-center gap-1.5 mb-1">
                      <Badge variant="secondary" className="text-[10px]">step {(stepIdx ?? 0) + 1}</Badge>
                      <span className="text-xs font-semibold">{detailStep.title}</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">{detailStep.note}</p>
                  </div>
                )}

                {detailStep && (
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                      AgentState 快照
                    </h4>
                    <div className="rounded-lg border bg-card p-2">
                      {Object.entries(detailStep.state).map(([k, v]) => (
                        <StateValue key={k} k={k} v={v} />
                      ))}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1">
                      <CornerDownLeft className="h-3 w-3" />
                      读入
                    </h4>
                    <div className="space-y-0.5">
                      {detailNode.inputs.length === 0 ? (
                        <span className="text-[11px] text-muted-foreground/60">—</span>
                      ) : (
                        detailNode.inputs.map((f) => (
                          <code key={f} className="text-[10.5px] block text-muted-foreground font-mono">{f}</code>
                        ))
                      )}
                    </div>
                  </div>
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1">
                      <ArrowRight className="h-3 w-3" />
                      写出
                    </h4>
                    <div className="space-y-0.5">
                      {detailNode.outputs.length === 0 ? (
                        <span className="text-[11px] text-muted-foreground/60">—</span>
                      ) : (
                        detailNode.outputs.map((f) => (
                          <code key={f} className="text-[10.5px] block text-muted-foreground font-mono">{f}</code>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                <Separator />

                <div>
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">源码</h4>
                  <code className="text-[10.5px] text-foreground/80 bg-muted px-2 py-1 rounded font-mono block">{detailNode.source}</code>
                </div>

                <div>
                  <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">后续路由</h4>
                  <div className="space-y-1">
                    {edges.filter((e) => e.source === detailNode.id).length === 0 ? (
                      <span className="text-[11px] text-muted-foreground/60">无出边</span>
                    ) : (
                      edges
                        .filter((e) => e.source === detailNode.id)
                        .map((e) => {
                          const tgt = nodeMap.get(e.target)
                          return (
                            <div key={e.id} className="flex items-center gap-1.5 text-[11px] py-1 px-1.5 rounded hover:bg-accent/50">
                              <ArrowRight className="h-3 w-3 text-muted-foreground/60 shrink-0" />
                              <span className="font-medium">{tgt?.label ?? e.target}</span>
                              {e.label && (
                                <code className="text-[10px] text-muted-foreground bg-muted px-1 py-0.5 rounded ml-auto">{e.label}</code>
                              )}
                              {e.disabled && <span className="text-[9px] text-slate-400 ml-auto">已禁用</span>}
                            </div>
                          )
                        })
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </div>
    </>
  )

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-[100] bg-background flex">
        {editor}
      </div>
    )
  }

  return <div className="flex h-full min-h-0">{editor}</div>
}
