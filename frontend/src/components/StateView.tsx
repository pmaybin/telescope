import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type Props = {
  icon: LucideIcon
  tone?: 'accent' | 'warning' | 'danger' | 'neutral'
  title: string
  role: 'alert' | 'status'
  children?: ReactNode
  actions?: ReactNode
}

/** Centred message used for empty, error and rate-limited states. */
export function StateView({
  icon: Icon,
  tone = 'neutral',
  title,
  role,
  children,
  actions,
}: Props) {
  return (
    <div className="state-view" role={role}>
      <span className="icon-circle" data-tone={tone}>
        <Icon size={26} aria-hidden="true" />
      </span>
      <h2>{title}</h2>
      {children}
      {actions && <div className="state-actions">{actions}</div>}
    </div>
  )
}
