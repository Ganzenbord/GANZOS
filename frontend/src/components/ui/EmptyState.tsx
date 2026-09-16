interface EmptyStateProps {
  title: string
  hint?: string
  actionLabel?: string
  onAction?: () => void
}

export function EmptyState({ title, hint, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {hint ? <p>{hint}</p> : null}
      {actionLabel ? (
        <button type="button" className="empty__action" onClick={onAction}>
          {actionLabel} <span aria-hidden>›</span>
        </button>
      ) : null}
    </div>
  )
}
