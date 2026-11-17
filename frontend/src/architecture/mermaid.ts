import type { Theme } from '../theme'

type Mermaid = typeof import('mermaid').default

let loading: Promise<Mermaid> | null = null
let queue: Promise<unknown> = Promise.resolve()
let counter = 0

/** Loads mermaid on first use so it stays out of the main bundle. */
export function loadMermaid(): Promise<Mermaid> {
  loading ??= import('mermaid').then((m) => m.default)
  return loading
}

/** Resolves a CSS token (including `light-dark()`) to a concrete colour. */
function resolveColor(name: string, fallback: string): string {
  const probe = document.createElement('span')
  probe.style.color = `var(${name})`
  probe.style.display = 'none'
  document.documentElement.appendChild(probe)
  const value = getComputedStyle(probe).color
  probe.remove()
  return value || fallback
}

/** Mermaid theme variables derived from the design tokens. */
export function themeVariables(theme: Theme): Record<string, string | boolean> {
  const dark = theme === 'dark'
  const c = (name: string, light: string, night: string) =>
    resolveColor(name, dark ? night : light)
  const surface = c('--surface', '#ffffff', '#12161c')
  const raised = c('--surface-raised', '#ffffff', '#181d24')
  const sunken = c('--surface-sunken', '#f0f2f5', '#0e1217')
  const border = c('--border', '#e2e5ea', '#252b34')
  const borderStrong = c('--border-strong', '#cdd2d9', '#363e49')
  const text = c('--text', '#14181f', '#e8ebf0')
  const muted = c('--text-muted', '#5b6472', '#98a1af')
  const accent = c('--accent', '#0369a1', '#38bdf8')
  const accentSoft = c('--accent-soft', '#e6f3fb', '#0c2434')
  const warningSoft = c('--warning-soft', '#fdf4dc', '#2c2208')
  const warningBorder = c('--warning-border', '#f0dc9b', '#5a4510')
  return {
    darkMode: dark,
    background: surface,
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif',
    fontSize: '14px',
    textColor: text,
    primaryColor: accentSoft,
    primaryTextColor: text,
    primaryBorderColor: accent,
    secondaryColor: sunken,
    secondaryTextColor: text,
    secondaryBorderColor: borderStrong,
    tertiaryColor: sunken,
    tertiaryTextColor: text,
    tertiaryBorderColor: borderStrong,
    mainBkg: accentSoft,
    nodeBorder: accent,
    nodeTextColor: text,
    lineColor: muted,
    clusterBkg: sunken,
    clusterBorder: borderStrong,
    titleColor: text,
    edgeLabelBackground: surface,
    noteBkgColor: warningSoft,
    noteBorderColor: warningBorder,
    noteTextColor: text,
    actorBkg: raised,
    actorBorder: accent,
    actorTextColor: text,
    actorLineColor: borderStrong,
    signalColor: muted,
    signalTextColor: text,
    labelBoxBkgColor: sunken,
    labelBoxBorderColor: borderStrong,
    labelTextColor: text,
    loopTextColor: text,
    activationBkgColor: accentSoft,
    activationBorderColor: accent,
    sequenceNumberColor: surface,
    classText: text,
    stateBkg: accentSoft,
    stateLabelColor: text,
    altBackground: sunken,
    transitionColor: muted,
    transitionLabelColor: text,
    specialStateColor: muted,
    compositeBackground: sunken,
    compositeBorder: borderStrong,
    compositeTitleBackground: raised,
    innerEndBackground: muted,
    border1: border,
  }
}

/**
 * Renders mermaid source to an SVG string. Calls are serialised because
 * `initialize` is global and must match the render it precedes.
 */
export function renderDiagram(source: string, theme: Theme): Promise<string> {
  const run = async () => {
    const mermaid = await loadMermaid()
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      themeVariables: themeVariables(theme),
      flowchart: { useMaxWidth: false },
      sequence: { useMaxWidth: false },
      class: { useMaxWidth: false },
      state: { useMaxWidth: false },
    })
    counter += 1
    const { svg } = await mermaid.render(`mmd-${counter}`, source)
    return svg
  }
  const result = queue.then(run, run)
  queue = result.catch(() => undefined)
  return result
}
