import type { ReactNode } from 'react'

interface PanelProps {
  title: string
  /** Korte sleutel; bepaalt op mobiel de volgorde (zie theme.css). */
  name?: string
  meta?: ReactNode
  linkLabel?: string
  onLink?: () => void
  children: ReactNode
  footer?: ReactNode
  tight?: boolean
}

export function Panel({ title, name, meta, linkLabel, onLink, children, footer, tight }: PanelProps) {
  return (
    <section className="panel" data-panel={name}>
      <header className="panel__head">
        <h2 className="panel__title">{title}</h2>
        {meta ? <div className="panel__meta">{meta}</div> : null}
        {linkLabel ? (
          <button type="button" className="panel__link" onClick={onLink}>
            {linkLabel} <span aria-hidden>›</span>
          </button>
        ) : null}
      </header>
      <div className={tight ? 'panel__body panel__body--tight' : 'panel__body'}>{children}</div>
      {footer ? <footer className="panel__foot">{footer}</footer> : null}
    </section>
  )
}
