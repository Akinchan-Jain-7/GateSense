import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from './button'

export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) {
    return <p className="px-4 py-3 text-xs text-muted tabular">{total.toString()} total</p>
  }
  const from = offset + 1
  const to = Math.min(offset + limit, total)
  return (
    <div className="flex items-center justify-between gap-2 px-4 py-3">
      <p className="text-xs text-muted tabular">
        {from.toString()}–{to.toString()} of {total.toString()}
      </p>
      <div className="flex gap-1">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset === 0}
          onClick={() => {
            onChange(Math.max(0, offset - limit))
          }}
          aria-label="Previous page"
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={to >= total}
          onClick={() => {
            onChange(offset + limit)
          }}
          aria-label="Next page"
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
