import { useState } from 'react'
import { Database, Network, FileText, Layers, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
    { icon: FileText, label: '向量数', value: stats?.milvus_vector_count ?? 0 },
    { icon: Network, label: '实体数', value: stats?.neo4j_entity_count ?? 0 },
    { icon: Database, label: '关系数', value: stats?.neo4j_relation_count ?? 0 },
    { icon: Layers, label: 'Chunk数', value: stats?.chunk_count ?? 0 },
  ]

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Database className="h-5 w-5" />
            系统状态
          </CardTitle>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={fetchStats}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3">
          {statItems.map((item) => (
            <div key={item.label} className="flex items-center gap-2 p-2 rounded-md bg-muted/50">
              <item.icon className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">{item.label}</p>
                {loading ? (
                  <Skeleton className="h-4 w-8" />
                ) : (
                  <p className="text-sm font-semibold">{item.value.toLocaleString()}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
