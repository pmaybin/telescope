import {
  Check,
  Code2,
  Copy,
  Download,
  Maximize2,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAppliedTheme } from '../theme'
import type { DiagramEntry } from './content'
import { DiagramViewer } from './DiagramViewer'
import { renderDiagram } from './mermaid'

type Render =
  | { status: 'loading' }
  | { status: 'ok'; svg: string }
  | { status: 'error'; message: string }

export function DiagramCard({ diagram }: { diagram: DiagramEntry }) {
  const theme = useAppliedTheme()
  const [render, setRender] = useState<Render>({ status: 'loading' })
  const [showSource, setShowSource] = useState(false)
  const [copied, setCopied] = useState(false)
  const [full, setFull] = useState(false)

  // Re-renders when the theme changes so the diagram follows light/dark.
  useEffect(() => {
    let cancelled = false
    renderDiagram(diagram.source, theme).then(
      (svg) => {
        if (!cancelled) setRender({ status: 'ok', svg })
      },
      (err: unknown) => {
        if (!cancelled)
          setRender({
            status: 'error',
            message: err instanceof Error ? err.message : String(err),
          })
      },
    )
    return () => {
      cancelled = true
    }
  }, [diagram.source, theme])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(diagram.source)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard unavailable: the source stays selectable */
    }
  }

  const download = () => {
    if (render.status !== 'ok') return
    const blob = new Blob([render.svg], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `telescope-${diagram.id}.svg`
    a.click()
    URL.revokeObjectURL(url)
  }

  const ready = render.status === 'ok'
  const sourceId = `source-${diagram.id}`

  return (
    <article
      className="card diagram-card"
      id={`diagram-${diagram.id}`}
      aria-labelledby={`diagram-${diagram.id}-title`}
    >
      <header className="diagram-head">
        <div className="diagram-title">
          <h3 id={`diagram-${diagram.id}-title`}>{diagram.title}</h3>
          <span className="kind-badge" data-kind={diagram.kind}>
            {diagram.kind}
          </span>
        </div>
        <p className="diagram-summary">{diagram.summary}</p>
        <div className="diagram-actions">
          <button
            type="button"
            className="btn btn-sm"
            aria-expanded={showSource}
            aria-controls={sourceId}
            onClick={() => setShowSource((v) => !v)}
          >
            <Code2 size={14} aria-hidden="true" />
            {showSource ? 'Hide source' : 'View source'}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={!ready}
            onClick={() => setFull(true)}
          >
            <Maximize2 size={14} aria-hidden="true" />
            Open full screen
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={!ready}
            onClick={download}
          >
            <Download size={14} aria-hidden="true" />
            Download SVG
          </button>
        </div>
      </header>

      {showSource && (
        <div className="source-block" id={sourceId}>
          <button
            type="button"
            className="btn btn-sm source-copy"
            onClick={copy}
          >
            {copied ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              <Copy size={14} aria-hidden="true" />
            )}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <pre>
            <code>{diagram.source}</code>
          </pre>
        </div>
      )}

      <div
        className="diagram-body"
        data-kind={diagram.kind}
        aria-busy={render.status === 'loading'}
      >
        {render.status === 'loading' && (
          <div
            className="diagram-skeleton"
            role="status"
            aria-label="Loading diagram"
          >
            <span className="skel" style={{ width: '38%' }} />
            <span className="skel" style={{ width: '64%', height: 120 }} />
            <span className="skel" style={{ width: '52%' }} />
          </div>
        )}
        {render.status === 'error' && (
          <div role="alert" className="diagram-error">
            <p className="alert-inline" data-tone="danger">
              <TriangleAlert size={14} aria-hidden="true" />
              <span>The diagram could not be rendered: {render.message}</span>
            </p>
            <pre>
              <code>{diagram.source}</code>
            </pre>
          </div>
        )}
        {render.status === 'ok' && (
          // Scaled to fit the card; click (or Enter) opens the zoomable viewer.
          <button
            type="button"
            className="diagram-fit"
            aria-label={`${diagram.title}: open full screen to zoom`}
            title="Click to open full screen and zoom"
            onClick={() => setFull(true)}
          >
            <span
              className="diagram-svg"
              role="img"
              aria-label={diagram.title}
              dangerouslySetInnerHTML={{ __html: render.svg }}
            />
            <span className="diagram-fit-hint" aria-hidden="true">
              <Maximize2 size={12} />
              Expand to zoom
            </span>
          </button>
        )}
      </div>

      {full && render.status === 'ok' && (
        <DiagramViewer
          title={diagram.title}
          svg={render.svg}
          onClose={() => setFull(false)}
        />
      )}
    </article>
  )
}
