import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  Play,
  Split,
  MessageCircle,
  Zap,
  Search,
  Share2,
  Database,
  PenLine,
  ShieldCheck,
  CircleStop,
  X,
  ZoomIn,
  ZoomOut,
  Maximize,
  LocateFixed,
  type LucideIcon,
} from 'lucide-react'
import {
  categoryColors,
  CANVAS_W,
  CANVAS_H,
  NODE_W,
  NODE_H,
  type WorkflowNode,
  type WorkflowEdge,
} from '@/data/workflowMock'

const iconMap: Record<string, LucideIcon> = {
  Play,
  Split,
  MessageCircle,
  Zap,
  Search,
  Share2,
  Database,
  PenLine,
  ShieldCheck,
  CircleStop,
}

interface Pt {
  x: number
  y: number
}

interface WorkflowGraphProps {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  activePathNodes: Set<string>
  activePathEdges: Set<string>
  currentNode: string | null
  selectedNode: string | null
  onNodeClick: (id: string) => void
  onNodeMove: (id: string, x: number, y: number) => void
  onDeleteNode: (id: string) => void
  onBackgroundClick?: () => void
}

function anchor(p: Pt, side: 'left' | 'right' | 'top' | 'bottom'): Pt {
  switch (side) {
    case 'left':
      return { x: p.x - NODE_W / 2, y: p.y }
    case 'right':
      return { x: p.x + NODE_W / 2, y: p.y }
    case 'top':
      return { x: p.x, y: p.y - NODE_H / 2 }
    case 'bottom':
      return { x: p.x, y: p.y + NODE_H / 2 }
  }
}

function edgePath(s: Pt, t: Pt, routing: 'straight' | 'top' | 'bottom') {
  if (routing === 'top') {
    const p1 = anchor(s, 'top')
    const p2 = anchor(t, 'top')
    const gap = 56
    return `M ${p1.x},${p1.y} C ${p1.x},${p1.y - gap} ${p2.x},${p2.y - gap} ${p2.x},${p2.y}`
  }
  if (routing === 'bottom') {
    const p1 = anchor(s, 'bottom')
    const p2 = anchor(t, 'bottom')
    const gap = 70
    return `M ${p1.x},${p1.y} C ${p1.x},${p1.y + gap} ${p2.x},${p2.y + gap} ${p2.x},${p2.y}`
  }
  const dx = t.x - s.x
  const dy = t.y - s.y
  if (Math.abs(dx) < 8) {
    if (dy > 0) {
      const p1 = anchor(s, 'bottom')
      const p2 = anchor(t, 'top')
      return `M ${p1.x},${p1.y} L ${p2.x},${p2.y}`
    }
    const p1 = anchor(s, 'top')
    const p2 = anchor(t, 'bottom')
    return `M ${p1.x},${p1.y} L ${p2.x},${p2.y}`
  }
  if (dx > 0) {
    const p1 = anchor(s, 'right')
    const p2 = anchor(t, 'left')
    const cp = Math.max(40, (p2.x - p1.x) * 0.5)
    return `M ${p1.x},${p1.y} C ${p1.x + cp},${p1.y} ${p2.x - cp},${p2.y} ${p2.x},${p2.y}`
  }
  const p1 = anchor(s, 'left')
  const p2 = anchor(t, 'right')
  const cp = Math.max(40, (p1.x - p2.x) * 0.5)
  return `M ${p1.x},${p1.y} C ${p1.x - cp},${p1.y} ${p2.x + cp},${p2.y} ${p2.x},${p2.y}`
}

function labelPos(s: Pt, t: Pt, routing: 'straight' | 'top' | 'bottom'): Pt {
  if (routing === 'top') return { x: (s.x + t.x) / 2, y: Math.min(s.y, t.y) - 52 }
  if (routing === 'bottom') return { x: (s.x + t.x) / 2, y: Math.max(s.y, t.y) + 64 }
  return { x: (s.x + t.x) / 2, y: (s.y + t.y) / 2 }
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
const ZOOM_MIN = 0.2
const ZOOM_MAX = 2.5

export function WorkflowGraph({
  nodes,
  edges,
  activePathNodes,
  activePathEdges,
  currentNode,
  selectedNode,
  onNodeClick,
  onNodeMove,
  onDeleteNode,
  onBackgroundClick,
}: WorkflowGraphProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [pan, setPan] = useState<Pt>({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [panning, setPanning] = useState(false)
  const [dragRender, setDragRender] = useState<{ id: string; x: number; y: number } | null>(null)

  // 最新 pan/zoom 的 ref，供原生事件处理器读取，避免闭包陈旧
  const latest = useRef({ pan, zoom })
  latest.current = { pan, zoom }

  const panStateRef = useRef<{
    startClientX: number
    startClientY: number
    startPanX: number
    startPanY: number
    moved: boolean
  } | null>(null)
  const dragStateRef = useRef<{
    id: string
    startX: number
    startY: number
    origX: number
    origY: number
    moved: boolean
    curX: number
    curY: number
  } | null>(null)

  const nodeMap = useMemo(() => {
    const m = new Map<string, WorkflowNode>()
    nodes.forEach((n) => m.set(n.id, n))
    return m
  }, [nodes])

  const posOf = (n: WorkflowNode): Pt => {
    if (dragRender && dragRender.id === n.id) return { x: dragRender.x, y: dragRender.y }
    return { x: n.x, y: n.y }
  }

  // ── 视图操作 ──
  const setZoomAround = (newZoom: number, cx: number, cy: number) => {
    const z = clamp(newZoom, ZOOM_MIN, ZOOM_MAX)
    const { pan: curPan, zoom: curZoom } = latest.current
    const worldX = (cx - curPan.x) / curZoom
    const worldY = (cy - curPan.y) / curZoom
    setPan({ x: cx - worldX * z, y: cy - worldY * z })
    setZoom(z)
  }

  const zoomByCenter = (factor: number) => {
    const el = viewportRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setZoomAround(latest.current.zoom * factor, rect.width / 2, rect.height / 2)
  }

  const resetView = () => {
    setPan({ x: 0, y: 0 })
    setZoom(1)
  }

  const fitView = () => {
    const el = viewportRef.current
    if (!el || nodes.length === 0) return
    const vw = el.clientWidth
    const vh = el.clientHeight
    const xs = nodes.map((n) => n.x)
    const ys = nodes.map((n) => n.y)
    const pad = 60
    const minX = Math.min(...xs) - NODE_W / 2 - pad
    const maxX = Math.max(...xs) + NODE_W / 2 + pad
    const minY = Math.min(...ys) - NODE_H / 2 - pad
    const maxY = Math.max(...ys) + NODE_H / 2 + pad
    const cw = maxX - minX
    const ch = maxY - minY
    const z = clamp(Math.min(vw / cw, vh / ch), ZOOM_MIN, ZOOM_MAX)
    setPan({ x: (vw - cw * z) / 2 - minX * z, y: (vh - ch * z) / 2 - minY * z })
    setZoom(z)
  }

  // 初始挂载后适应视图
  useLayoutEffect(() => {
    fitView()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 原生非被动 wheel 监听，确保 preventDefault 生效
  useLayoutEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const cx = e.clientX - rect.left
      const cy = e.clientY - rect.top
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
      setZoomAround(latest.current.zoom * factor, cx, cy)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // ── 画布平移（拖拽空白） ──
  const onViewportPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    const { pan: curPan } = latest.current
    panStateRef.current = {
      startClientX: e.clientX,
      startClientY: e.clientY,
      startPanX: curPan.x,
      startPanY: curPan.y,
      moved: false,
    }
    setPanning(true)

    const onMove = (ev: PointerEvent) => {
      const st = panStateRef.current
      if (!st) return
      const dx = ev.clientX - st.startClientX
      const dy = ev.clientY - st.startClientY
      if (!st.moved && Math.hypot(dx, dy) < 3) return
      st.moved = true
      setPan({ x: st.startPanX + dx, y: st.startPanY + dy })
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      const st = panStateRef.current
      panStateRef.current = null
      setPanning(false)
      if (st && !st.moved) onBackgroundClick?.()
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  // ── 节点拖拽 ──
  const onNodePointerDown = (e: React.PointerEvent, n: WorkflowNode) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    dragStateRef.current = {
      id: n.id,
      startX: e.clientX,
      startY: e.clientY,
      origX: n.x,
      origY: n.y,
      moved: false,
      curX: n.x,
      curY: n.y,
    }
    setDragRender({ id: n.id, x: n.x, y: n.y })

    const onMove = (ev: PointerEvent) => {
      const st = dragStateRef.current
      if (!st) return
      const zz = latest.current.zoom
      const dx = (ev.clientX - st.startX) / zz
      const dy = (ev.clientY - st.startY) / zz
      if (!st.moved && Math.hypot(dx, dy) < 3) return
      st.moved = true
      st.curX = clamp(st.origX + dx, NODE_W / 2, CANVAS_W - NODE_W / 2)
      st.curY = clamp(st.origY + dy, NODE_H / 2, CANVAS_H - NODE_H / 2)
      setDragRender({ id: st.id, x: st.curX, y: st.curY })
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      const st = dragStateRef.current
      dragStateRef.current = null
      setDragRender(null)
      if (!st) return
      if (st.moved) onNodeMove(st.id, st.curX, st.curY)
      else onNodeClick(st.id)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <div
      ref={viewportRef}
      onPointerDown={onViewportPointerDown}
      className={`relative h-full w-full overflow-hidden bg-muted/20 ${panning ? 'cursor-grabbing' : 'cursor-grab'}`}
      style={{ touchAction: 'none' }}
    >
      {/* 世界层（平移 + 缩放） */}
      <div
        className="absolute top-0 left-0 origin-top-left"
        style={{
          width: CANVAS_W,
          height: CANVAS_H,
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          backgroundImage:
            'radial-gradient(circle, hsl(var(--border)) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          backgroundColor: 'hsl(var(--card))',
          boxShadow: '0 0 0 1px hsl(var(--border))',
        }}
      >
        {/* ── SVG 边层 ── */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width={CANVAS_W}
          height={CANVAS_H}
          style={{ overflow: 'visible' }}
        >
          <defs>
            <marker id="arrow-default" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
            </marker>
            <marker id="arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#3b82f6" />
            </marker>
            <marker id="arrow-dim" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1" />
            </marker>
          </defs>

          {edges.map((e: WorkflowEdge) => {
            const sNode = nodeMap.get(e.source)
            const tNode = nodeMap.get(e.target)
            if (!sNode || !tNode) return null
            const s = posOf(sNode)
            const t = posOf(tNode)
            const routing = e.routing ?? 'straight'
            const d = edgePath(s, t, routing)
            const isActive = activePathEdges.has(e.id)
            const isDisabled = e.disabled

            let stroke = '#94a3b8'
            let strokeWidth = 1.6
            let marker = 'arrow-default'
            let opacity = 0.9
            if (isDisabled) {
              stroke = '#cbd5e1'
              strokeWidth = 1.2
              marker = 'arrow-dim'
              opacity = 0.55
            }
            if (isActive) {
              stroke = '#3b82f6'
              strokeWidth = 2.4
              marker = 'arrow-active'
              opacity = 1
            }

            const lp = labelPos(s, t, routing)

            return (
              <g key={e.id} opacity={opacity}>
                <path
                  d={d}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  strokeDasharray={e.dashed ? '5 4' : undefined}
                  markerEnd={`url(#${marker})`}
                  className={isActive && e.dashed ? 'wf-flow-dash' : undefined}
                  style={
                    isActive && !e.dashed
                      ? { filter: 'drop-shadow(0 0 4px rgba(59,130,246,0.45))' }
                      : undefined
                  }
                />
                {e.label && (
                  <g>
                    <rect
                      x={lp.x - (e.label.length * 6.2 + 8) / 2}
                      y={lp.y - 9}
                      width={e.label.length * 6.2 + 8}
                      height={18}
                      rx={9}
                      fill="hsl(var(--background))"
                      stroke={isActive ? '#3b82f6' : '#e2e8f0'}
                      strokeWidth={1}
                    />
                    <text
                      x={lp.x}
                      y={lp.y + 4}
                      textAnchor="middle"
                      fontSize={10.5}
                      fill={isDisabled ? '#94a3b8' : isActive ? '#1d4ed8' : '#64748b'}
                      fontFamily="ui-monospace, monospace"
                    >
                      {e.label}
                    </text>
                  </g>
                )}
              </g>
            )
          })}
        </svg>

        {/* ── HTML 节点层 ── */}
        {nodes.map((n) => {
          const color = categoryColors[n.category]
          const Icon = iconMap[n.icon] ?? Play
          const inPath = activePathNodes.has(n.id)
          const isCurrent = currentNode === n.id
          const isSelected = selectedNode === n.id
          const isDisabled = n.disabled
          const p = posOf(n)
          const isDragging = dragRender?.id === n.id

          return (
            <div
              key={n.id}
              onPointerDown={(e) => onNodePointerDown(e, n)}
              className={`absolute rounded-xl border bg-card transition-shadow duration-200 ${
                isDisabled ? 'opacity-50' : 'hover:shadow-md'
              } ${isDragging ? 'shadow-lg cursor-grabbing' : 'cursor-grab'}`}
              style={{
                left: p.x - NODE_W / 2,
                top: p.y - NODE_H / 2,
                width: NODE_W,
                height: NODE_H,
                borderColor: isSelected ? color.bar : inPath ? color.ring : 'hsl(var(--border))',
                borderWidth: isSelected ? 2 : 1,
                boxShadow: isCurrent
                  ? `0 0 0 3px ${color.bar}40, 0 4px 14px ${color.bar}30`
                  : isDragging
                    ? `0 8px 24px rgba(0,0,0,0.15)`
                    : undefined,
                zIndex: isDragging ? 20 : isCurrent || isSelected ? 10 : 1,
                touchAction: 'none',
              }}
            >
              <span
                className="absolute left-0 top-0 bottom-0 w-1 rounded-l-xl"
                style={{ background: color.bar, opacity: isDisabled ? 0.4 : 1 }}
              />
              {isCurrent && (
                <span
                  className="absolute -inset-0.5 rounded-xl pointer-events-none animate-pulse"
                  style={{ boxShadow: `0 0 0 2px ${color.bar}` }}
                />
              )}
              {isSelected && (
                <button
                  type="button"
                  title="删除节点"
                  onPointerDown={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                  }}
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteNode(n.id)
                  }}
                  className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center shadow-md hover:scale-110 transition-transform z-30"
                >
                  <X style={{ width: 11, height: 11 }} />
                </button>
              )}
              <div className="h-full flex items-center gap-2.5 pl-3.5 pr-3 pointer-events-none">
                <span
                  className="shrink-0 w-9 h-9 rounded-lg flex items-center justify-center"
                  style={{ background: color.soft, color: color.text }}
                >
                  <Icon style={{ width: 18, height: 18 }} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-semibold text-foreground truncate">{n.label}</span>
                    {n.fallback && !n.disabled && (
                      <span className="text-[9px] px-1 py-px rounded bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300 shrink-0">
                        兜底
                      </span>
                    )}
                    {n.disabled && (
                      <span className="text-[9px] px-1 py-px rounded bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400 shrink-0">
                        已禁用
                      </span>
                    )}
                  </div>
                  <code className="text-[10.5px] text-muted-foreground font-mono truncate block">
                    {n.codeName}
                  </code>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* ── 视图控制浮层 ── */}
      <div className="absolute bottom-3 right-3 flex items-center gap-1 rounded-lg border bg-card/90 backdrop-blur px-1 py-1 shadow-md z-50">
        <button
          type="button"
          onClick={() => zoomByCenter(1 / 1.2)}
          title="缩小"
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
        >
          <ZoomOut style={{ width: 15, height: 15 }} />
        </button>
        <span className="text-[11px] tabular-nums text-muted-foreground w-10 text-center select-none">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          onClick={() => zoomByCenter(1.2)}
          title="放大"
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
        >
          <ZoomIn style={{ width: 15, height: 15 }} />
        </button>
        <span className="w-px h-5 bg-border mx-0.5" />
        <button
          type="button"
          onClick={fitView}
          title="适应内容"
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
        >
          <Maximize style={{ width: 14, height: 14 }} />
        </button>
        <button
          type="button"
          onClick={resetView}
          title="重置视图"
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-accent text-muted-foreground hover:text-foreground"
        >
          <LocateFixed style={{ width: 14, height: 14 }} />
        </button>
      </div>

      <style>{`
        .wf-flow-dash {
          stroke-dasharray: 6 4;
          animation: wf-dash 0.8s linear infinite;
        }
        @keyframes wf-dash {
          to { stroke-dashoffset: -20; }
        }
      `}</style>
    </div>
  )
}
