import { ReactNode } from 'react'

/**
 * SQL 查询结果数据表（统一预览组件）。
 *
 * 全局约定：只预览前 5 行，空结果显示 "(空结果)"，总行数超过预览时显示 "… 共 N 行"。
 * 用于：
 * - ChatMessage 处理过程 sql_agent step 的「数据预览」
 * - SearchDebugPanel SQL agent step 的「结果预览」
 * - SearchDebugPanel SqlDebugView 的「执行结果」
 */
export interface SqlResultTableProps {
  /** 列名（数据库字段名） */
  columns: string[]
  /** 数据行（每行为值数组，顺序与 columns 对应） */
  rows: unknown[][]
  /** 总行数（用于 "X/Y 行" 与溢出提示），默认 = rows.length */
  rowCount?: number
  /** 预览行数上限，默认 5 */
  previewLimit?: number
  /** 是否显示 # 序号列，默认 false */
  showIndex?: boolean
  /** 字号档位：sm=text-xs（默认），xs=text-[10px]（紧凑） */
  size?: 'sm' | 'xs'
  /** 空结果文案，默认 "(空结果)" */
  emptyText?: string
  /** 溢出追加提示（追加在 "… 共 N 行" 后），可选 */
  overflowHint?: string
  className?: string
  /** 自定义标题区（显示在表格上方的 "X/Y 行" 提示行），传 null 则隐藏 */
  caption?: ReactNode | null
}

export function SqlResultTable({
  columns,
  rows,
  rowCount,
  previewLimit = 5,
  showIndex = false,
  size = 'sm',
  emptyText = '(空结果)',
  overflowHint,
  className,
  caption,
}: SqlResultTableProps) {
  if (!columns || columns.length === 0) return null

  const total = Number(rowCount ?? rows.length)
  const limit = Math.max(0, previewLimit)
  const textCls = size === 'xs' ? 'text-[10px]' : 'text-xs'
  const cellCls = 'border border-border/50 px-1.5 py-0.5 font-mono whitespace-nowrap'
  const previewRows = rows.slice(0, limit)
  const showOverflow = total > previewRows.length

  // 默认 caption：X/Y 行
  const defaultCaption = (
    <div className={`${textCls} text-muted-foreground mb-0.5`}>
      {Math.min(previewRows.length, limit)}/{total} 行
    </div>
  )

  return (
    <div className={`overflow-x-auto ${className || ''}`}>
      {caption !== null && (caption || defaultCaption)}
      <table className={`w-full border-collapse ${textCls}`}>
        <thead>
          <tr className="bg-muted/50">
            {showIndex && (
              <th className={`${cellCls} text-left text-muted-foreground`}>#</th>
            )}
            {columns.map((c, ci) => (
              <th key={ci} className={`${cellCls} text-left`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {previewRows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (showIndex ? 1 : 0)}
                className={`${cellCls} text-muted-foreground italic`}
              >
                {emptyText}
              </td>
            </tr>
          ) : (
            previewRows.map((row, ri) => {
              const cells = Array.isArray(row) ? row : [row]
              return (
                <tr key={ri}>
                  {showIndex && (
                    <td className={`${cellCls} text-muted-foreground`}>{ri + 1}</td>
                  )}
                  {cells.map((val, vi) => (
                    <td key={vi} className={cellCls}>{String(val ?? '')}</td>
                  ))}
                </tr>
              )
            })
          )}
          {showOverflow && (
            <tr>
              <td
                colSpan={columns.length + (showIndex ? 1 : 0)}
                className={`${cellCls} text-muted-foreground italic`}
              >
                … 共 {total} 行{overflowHint ? `，${overflowHint}` : ''}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
