import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react'
import type { ProgressivePage } from '../api/progressive'
import { isComplete } from '../api/progressive'
import { formatNumber } from '../format'
import type { Patch } from './FilterBar'

type Props = {
  data: ProgressivePage
  paging: 'cursor' | 'offset'
  offset: number
  limit: number
  onChange: (patch: Patch) => void
}

function IconButton({
  label,
  title,
  disabled,
  onClick,
  children,
}: {
  label: string
  title: string
  disabled: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      className="btn btn-icon btn-sm"
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

export function Pagination({ data, paging, offset, limit, onChange }: Props) {
  const total = data.page.total
  const count = data.items.length
  const offsetMode = paging === 'offset'
  const range =
    count === 0
      ? '0'
      : offsetMode
        ? `${formatNumber(offset + 1)}–${formatNumber(offset + count)}`
        : formatNumber(count)
  const loading = !isComplete(data)
  const known = total !== null
  const pages = known ? Math.max(1, Math.ceil(total / limit)) : 1
  const lastOffset = (pages - 1) * limit
  const atEnd = loading || !known || offset + limit >= total
  const wait = 'Available once loading finishes'

  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        Showing <strong>{range}</strong>
        {known && (
          <>
            {' '}
            of <strong>{formatNumber(total)}</strong>
          </>
        )}
      </span>
      {offsetMode ? (
        <div className="pager-controls">
          <IconButton
            label="First"
            title={loading ? wait : 'First page'}
            disabled={loading || offset === 0}
            onClick={() => onChange({ offset: undefined })}
          >
            <ChevronsLeft size={16} />
          </IconButton>
          <IconButton
            label="Prev"
            title={loading ? wait : 'Previous page'}
            disabled={loading || offset === 0}
            onClick={() =>
              onChange({ offset: String(Math.max(0, offset - limit)) })
            }
          >
            <ChevronLeft size={16} />
          </IconButton>
          <span className="page-indicator">
            {known
              ? `Page ${formatNumber(Math.floor(offset / limit) + 1)} of ${formatNumber(pages)}`
              : `Page ${formatNumber(Math.floor(offset / limit) + 1)}`}
          </span>
          <IconButton
            label="Next"
            title={loading ? wait : 'Next page'}
            disabled={atEnd}
            onClick={() => onChange({ offset: String(offset + limit) })}
          >
            <ChevronRight size={16} />
          </IconButton>
          <IconButton
            label="Last"
            title={loading ? wait : 'Last page'}
            disabled={atEnd}
            onClick={() => onChange({ offset: String(lastOffset) })}
          >
            <ChevronsRight size={16} />
          </IconButton>
        </div>
      ) : (
        <div className="pager-controls">
          <IconButton
            label="Prev"
            title={loading ? wait : 'Previous page'}
            disabled={loading || !data.page.has_prev || !data.page.prev_cursor}
            onClick={() =>
              onChange({ cursor: data.page.prev_cursor ?? undefined })
            }
          >
            <ChevronLeft size={16} />
          </IconButton>
          <IconButton
            label="Next"
            title={loading ? wait : 'Next page'}
            disabled={loading || !data.page.has_next || !data.page.next_cursor}
            onClick={() =>
              onChange({ cursor: data.page.next_cursor ?? undefined })
            }
          >
            <ChevronRight size={16} />
          </IconButton>
        </div>
      )}
    </nav>
  )
}
