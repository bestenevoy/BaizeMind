import { useEffect, useRef, useCallback } from 'react'
import { Network } from 'vis-network'
import { DataSet } from 'vis-data'
import { getGraphOverview, type GraphOverview } from '@/lib/api'

const typeColors: Record<string, string> = {
  Person: '#4C97FF',
  Organization: '#FF8C00',
  Product: '#59A059',
  Technology: '#CF63CF',
  Location: '#C94D46',
  Event: '#5CB1D6',
  Concept: '#A09C5C',
}

interface GraphViewProps {
  docId?: string
  onNodeClick?: (nodeId: string) => void
  selectedNode?: string | null
}

export function GraphView({ docId, onNodeClick, selectedNode }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)
  const onNodeClickRef = useRef(onNodeClick)

  onNodeClickRef.current = onNodeClick

  const buildGraph = useCallback(async () => {
    if (!containerRef.current) return
    let data: GraphOverview
    try {
      data = await getGraphOverview(docId || undefined)
    } catch (e) {
      console.error('Failed to load graph data:', e)
      return
    }

    if (!data.nodes.length) {
      if (containerRef.current) {
        containerRef.current.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-size:14px">暂无图谱数据</div>'
      }
      return
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodes = new DataSet<any, 'id'>(
      data.nodes.map((n) => ({
        id: n.id,
        label: n.label.length > 12 ? n.label.slice(0, 12) + '...' : n.label,
        title: `<b>${n.label}</b><br/>类型: ${n.type || 'Unknown'}<br/>${n.description || ''}`,
        color: typeColors[n.type] || '#97AAB3',
        font: { size: 14, color: '#333' },
        borderWidth: 2,
        size: 25,
      }))
    )

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const edges = new DataSet<any, 'id'>(
      data.edges.map((e, i) => ({
        id: `e${i}`,
        from: e.source,
        to: e.target,
        label: e.type,
        arrows: 'to',
        color: { color: '#C0C0C0', highlight: '#4C97FF' },
        font: { size: 9, color: '#666', strokeWidth: 2, strokeColor: '#fff' },
        smooth: { enabled: true, type: 'continuous', roundness: 0.5 },
      }))
    )

    if (networkRef.current) {
      networkRef.current.destroy()
    }

    networkRef.current = new Network(containerRef.current, { nodes, edges }, {
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -50,
          centralGravity: 0.01,
          springLength: 200,
          springConstant: 0.08,
        },
        stabilization: { iterations: 150 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        zoomView: true,
        dragView: true,
      },
      layout: {
        improvedLayout: false,
      },
      nodes: {
        shape: 'dot',
        scaling: {
          min: 15,
          max: 40,
          label: { enabled: true, min: 12, max: 24 },
        },
      },
      edges: {
        width: 2,
        selectionWidth: 3,
      },
    })

    networkRef.current.on('click', (params: { nodes: string[] }) => {
      if (params.nodes.length > 0 && onNodeClickRef.current) {
        onNodeClickRef.current(params.nodes[0])
      }
    })
  }, [docId])

  useEffect(() => {
    buildGraph()
    return () => {
      if (networkRef.current) {
        networkRef.current.destroy()
        networkRef.current = null
      }
    }
  }, [buildGraph])

  useEffect(() => {
    if (!networkRef.current || !selectedNode) return
    try {
      networkRef.current.selectNodes([selectedNode])
      networkRef.current.focus(selectedNode, { scale: 1.2, animation: true })
    } catch {
      // ignore
    }
  }, [selectedNode])

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg border"
      style={{ height: '100%', minHeight: '500px' }}
    />
  )
}
