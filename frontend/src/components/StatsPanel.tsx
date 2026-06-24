import { useState } from 'react'
import { Database, Network, FileText, Layers, RefreshCw } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { getSystemStats, type SystemStats } from '@/lib/api'
import { useEffect } from 'react'

export function StatsPanel() {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStats = async () => {
    setLoading(true)
    try {
      const data = await getSystemStats()
      setStats(data)
    } catch {
      setStats(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStats()
  }, [])

  const statItems = [
    { icon: FileText, label: '向量数', value: stats?.milvus_vector_count ?? 0, gradient: 'var(--gradient-stat-1)' },
    { icon: Network, label: '实体数', value: stats?.neo4j_entity_count ?? 0, gradient: 'var(--gradient-stat-2)' },
    { icon: Database, label: '关系数', value: stats?.neo4j_relation_count ?? 0, gradient: 'var(--gradient-stat-3)' },
    { icon: Layers, label: 'Chunk数', value: stats?.chunk_count ?? 0, gradient: 'var(--gradient-stat-4)' },
  ]

  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-muted-foreground">系统状态</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={fetchStats}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {statItems.map((item) => (
            <div key={item.label} className="flex items-center gap-2.5 p-2 rounded-lg bg-muted/40">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: item.gradient }}
              >
                <item.icon className="h-4 w-4 text-white" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] text-muted-foreground truncate">{item.label}</p>
                {loading ? (
                  <Skeleton className="h-4 w-10" />
                ) : (
                  <p className="text-sm font-semibold tabular-nums">{item.value.toLocaleString()}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
