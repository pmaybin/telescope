import { Maximize2, Minus, Plus, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent } from 'react'

type View = { x: number; y: number; k: number }

const MIN_K = 0.05
const MAX_K = 10

/** Natural size of an SVG string, read from its viewBox. */
function svgSize(svg: string): { w: number; h: number } {
  const m =
    /viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"/.exec(svg)
  return m ? { w: Number(m[1]), h: Number(m[2]) } : { w: 1000, h: 600 }
}

/** Full-screen modal: wheel to zoom, drag to pan, reset to fit. */
export function DiagramViewer({
  title,
  svg,
  onClose,
}: {
  title: string
  svg: string
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  const { w, h } = svgSize(svg)

  const fit = useCallback(() => {
    const stage = stageRef.current
    if (!stage) return
    const { width, height } = stage.getBoundingClientRect()
    if (width === 0 || height === 0) return
    const k = Math.min((width * 0.96) / w, (height * 0.96) / h, 2)
    setView({ k, x: (width - w * k) / 2, y: (height - h * k) / 2 })
  }, [w, h])

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open && typeof dialog.showModal === 'function') {
      dialog.showModal()
    }
    const stage = stageRef.current
    if (!stage || typeof ResizeObserver === 'undefined') return
    // Fits once the dialog has a layout, and again if the window is resized.
    const obs = new ResizeObserver(fit)
    obs.observe(stage)
    return () => obs.disconnect()
  }, [fit])

  // A non-passive listener is needed to stop the page scrolling while zooming.
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = stage.getBoundingClientRect()
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      setView((v) => {
        const k = Math.min(
          MAX_K,
          Math.max(MIN_K, v.k * Math.exp(-e.deltaY * 0.0015)),
        )
        const r = k / v.k
        return { k, x: px - (px - v.x) * r, y: py - (py - v.y) * r }
      })
    }
    stage.addEventListener('wheel', onWheel, { passive: false })
    return () => stage.removeEventListener('wheel', onWheel)
  }, [])

  const zoomBy = (factor: number) => {
    const stage = stageRef.current
    if (!stage) return
    const rect = stage.getBoundingClientRect()
    const px = rect.width / 2
    const py = rect.height / 2
    setView((v) => {
      const k = Math.min(MAX_K, Math.max(MIN_K, v.k * factor))
      const r = k / v.k
      return { k, x: px - (px - v.x) * r, y: py - (py - v.y) * r }
    })
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY }
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    drag.current = { x: e.clientX, y: e.clientY }
    setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }))
  }
  const onPointerUp = () => {
    drag.current = null
  }

  const canvasStyle = {
    '--w': `${w}px`,
    '--h': `${h}px`,
    transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
  } as CSSProperties

  return (
    <dialog
      ref={dialogRef}
      className="viewer"
      aria-label={`${title}, full screen`}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="viewer-bar">
        <h3>{title}</h3>
        <span className="viewer-hint">Scroll to zoom, drag to pan</span>
        <span className="viewer-zoom" aria-live="polite">
          {Math.round(view.k * 100)}%
        </span>
        <button
          type="button"
          className="btn btn-icon btn-sm"
          aria-label="Zoom out"
          onClick={() => zoomBy(1 / 1.3)}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          className="btn btn-icon btn-sm"
          aria-label="Zoom in"
          onClick={() => zoomBy(1.3)}
        >
          <Plus size={16} />
        </button>
        <button type="button" className="btn btn-sm" onClick={fit}>
          <Maximize2 size={14} aria-hidden="true" />
          Reset
        </button>
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={onClose}
        >
          <X size={14} aria-hidden="true" />
          Close
        </button>
      </div>
      <div
        ref={stageRef}
        className="viewer-stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="viewer-canvas"
          style={canvasStyle}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </dialog>
  )
}
