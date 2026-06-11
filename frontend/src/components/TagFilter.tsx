import { useEffect, useState } from 'react'
import { Tag, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { listTags, type TagInfo } from '@/lib/api'

interface TagFilterProps {
  selectedTags: string[]
  onToggle: (tag: string) => void
  onRefresh?: () => void
}

export function TagFilter({ selectedTags, onToggle, onRefresh }: TagFilterProps) {
  const [tags, setTags] = useState<TagInfo[]>([])

  const fetchTags = () => {
    listTags().then(setTags).catch(() => {})
  }

  useEffect(() => {
    fetchTags()
  }, [])

  useEffect(() => {
    if (onRefresh) onRefresh = fetchTags
  }, [onRefresh])

  if (tags.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Tag className="h-4 w-4" />
          标签
        </CardTitle>
      </CardHeader>
      <CardContent className="p-2">
        <div className="flex flex-wrap gap-1.5">
          {tags.map((t) => {
            const active = selectedTags.includes(t.tag)
            return (
              <Badge
                key={t.tag}
                variant={active ? 'default' : 'outline'}
                className="cursor-pointer text-xs transition-colors"
                onClick={() => onToggle(t.tag)}
              >
                {t.tag}
                <span className="ml-1 opacity-60">{t.count}</span>
                {active && <X className="ml-1 h-3 w-3" />}
              </Badge>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
